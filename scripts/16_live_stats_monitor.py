#!/usr/bin/env python3
"""
Script 16 v2 · LoL 实时战局监控（领先 Polymarket 价格变动）

【v2 核心重新设计】
  v1 的问题：触发条件依赖 Polymarket 赔率在 8~42% 范围内
              → 等于等 Polymarket 先动了才通知，本质上还是滞后

  v2 的解决：信号完全基于 LiveStats 实时战局数据触发（金差、时间、抑制器）
              Polymarket 赔率仅在通知中显示为参考信息
              → 在 Polymarket 动价「之前」就发出通知

工作流程（每 15 秒）：
  1. getLive API  → 找正在进行的 LCK/LPL/LEC/LCS 场次
  2. window API   → 读实时金差、击杀、塔、龙（HTTP 204 = 局间等待，安全跳过）
  3. 信号评估     → 金差可控 + 游戏时间够 + 无抑制器 → 立即通知
  4. Polymarket   → 每 90 秒刷新一次缓存，仅用于在通知中显示当前参考价

通知含义：
  - Poly未更新⚡  → Polymarket 价格仍然偏高，可能是最佳入场窗口
  - Poly部分更新  → 赔率已开始移动，仍有机会但窗口在收窄
  - Poly已更新    → 赔率已经很低，市场已消化，核实后再决定
"""

import json
import subprocess
import time
from datetime import datetime
from difflib import SequenceMatcher

import requests
import urllib3

urllib3.disable_warnings()

# ══════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════

INTERVAL        = 15    # LiveStats 轮询间隔（秒）
POLY_REFRESH    = 90    # Polymarket 缓存刷新间隔（秒）
NOTIFY_COOLDOWN = 180   # 同一场次同一队，3 分钟内不重复通知

GOLD_DIFF_MAX   = 3000  # 落后超过 3000 金不通知（翻盘概率极低）
MIN_GAME_MIN    = 8     # 前 8 分钟忽略开局噪音

API_KEY     = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
LOL_HEADERS = {"x-api-key": API_KEY}

TARGET_LEAGUES = {"LCK", "LPL", "LEC", "LCS"}

# ── 运行时状态 ──
_notified:         dict[tuple, float]    = {}   # (game_id, side) → 上次通知时间
_poly_cache:       dict[str, dict|None]  = {}   # "blue|red" → Polymarket 数据
_poly_last_refresh: float                = 0.0  # 上次 Polymarket 刷新时间
_known_game_ids:   set[str]              = set() # 已出现过的 game_id（用于新场次检测）

# ══════════════════════════════════════════════════════════════════
# macOS 通知
# ══════════════════════════════════════════════════════════════════

def notify(title: str, body: str, sound: str = "Ping") -> None:
    title = title.replace('"', "'")
    body  = body.replace('"', "'")
    script = f'display notification "{body}" with title "{title}" sound name "{sound}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] 🔔  {title}")
    print(f"         {body}")

# ══════════════════════════════════════════════════════════════════
# LoL Esports API
# ══════════════════════════════════════════════════════════════════

def get_live_games() -> list[dict]:
    """返回所有正在进行的目标联赛场次，含队伍信息和系列赛比分"""
    try:
        r = requests.get(
            "https://esports-api.lolesports.com/persisted/gw/getLive",
            params={"hl": "en-US"},
            headers=LOL_HEADERS,
            timeout=12,
            verify=False,
        )
        r.raise_for_status()
        events = r.json().get("data", {}).get("schedule", {}).get("events", [])
    except Exception as e:
        print(f"[{datetime.now():%H:%M:%S}] ⚠️  getLive 错误: {e}")
        return []

    result = []
    for ev in events:
        league = ev.get("league", {}).get("name", "")
        if league not in TARGET_LEAGUES:
            continue
        teams = ev.get("match", {}).get("teams", [])
        games = ev.get("match", {}).get("games", [])
        live_game = next((g for g in games if g.get("state") == "inProgress"), None)
        if not live_game or len(teams) < 2:
            continue

        blue_team = teams[0]
        red_team  = teams[1]
        result.append({
            "game_id":   live_game.get("id", ""),
            "league":    league,
            "blue":      {
                "name": blue_team.get("name", ""),
                "code": blue_team.get("code", ""),
                "id":   blue_team.get("id", ""),
            },
            "red":       {
                "name": red_team.get("name", ""),
                "code": red_team.get("code", ""),
                "id":   red_team.get("id", ""),
            },
            "blue_wins": blue_team.get("result", {}).get("gameWins", 0),
            "red_wins":  red_team.get("result", {}).get("gameWins", 0),
        })
    return result


def get_game_state(game_id: str) -> dict | None:
    """
    从 window API 获取最新帧数据。

    重要：两局之间 API 返回 HTTP 204（无内容），这是正常情况，
    直接返回 None，不打印错误，不影响进程继续运行。
    """
    try:
        r = requests.get(
            f"https://feed.lolesports.com/livestats/v1/window/{game_id}",
            headers=LOL_HEADERS,
            timeout=12,
            verify=False,
        )
        if r.status_code == 204:
            # 局间等待期，正常，静默跳过
            return None
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.HTTPError as e:
        print(f"[{datetime.now():%H:%M:%S}] ⚠️  window HTTP 错误 (game ...{game_id[-6:]}): {e}")
        return None
    except Exception as e:
        print(f"[{datetime.now():%H:%M:%S}] ⚠️  window API 错误 (game ...{game_id[-6:]}): {e}")
        return None

    frames = data.get("frames", [])
    if not frames:
        return None

    frame = frames[-1]
    bt = frame.get("blueTeam", {})
    rt = frame.get("redTeam", {})

    # 游戏时间估算：
    # 初始双方各 500 金（10人=5000），之后每分钟约增加 3500 金
    total_gold    = bt.get("totalGold", 0) + rt.get("totalGold", 0)
    game_time_min = max(0.0, (total_gold - 5000) / 3500)

    return {
        "game_time_min":   round(game_time_min, 1),
        "blue_gold":       bt.get("totalGold", 0),
        "red_gold":        rt.get("totalGold", 0),
        "gold_diff":       bt.get("totalGold", 0) - rt.get("totalGold", 0),
        "blue_kills":      bt.get("totalKills", 0),
        "red_kills":       rt.get("totalKills", 0),
        "blue_towers":     bt.get("towers", 0),
        "red_towers":      rt.get("towers", 0),
        "blue_dragons":    len(bt.get("dragons", [])),
        "red_dragons":     len(rt.get("dragons", [])),
        "blue_inhibitors": bt.get("inhibitors", 0),
        "red_inhibitors":  rt.get("inhibitors", 0),
        "timestamp":       frame.get("rfc460Timestamp", ""),
    }

# ══════════════════════════════════════════════════════════════════
# Polymarket 价格缓存（独立刷新，不阻塞战局轮询）
# ══════════════════════════════════════════════════════════════════

def _normalize(name: str) -> str:
    return name.lower().replace(" ", "").replace(".", "").replace("'", "")

def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()

def refresh_polymarket_cache(games: list[dict]) -> None:
    """
    批量刷新所有直播场次的 Polymarket 市场数据。
    每 POLY_REFRESH 秒调用一次，不在每次战局轮询时调用。
    """
    global _poly_last_refresh

    EXCLUDE_KW = ["season", "winner", "champion", "challenger", "spring",
                  "summer", "split", "playoff", "worlds", "msi", "region"]
    TAG_SLUGS  = ["league-of-legends", "esports"]

    # 拉取所有活跃事件
    all_events, seen_ids = [], set()
    for tag in TAG_SLUGS:
        try:
            r = requests.get(
                "https://gamma-api.polymarket.com/events",
                params={"active": "true", "closed": "false", "archived": "false",
                        "tag_slug": tag, "limit": 100},
                timeout=12,
            )
            r.raise_for_status()
            for ev in r.json():
                if ev.get("id") not in seen_ids:
                    seen_ids.add(ev.get("id"))
                    all_events.append(ev)
        except Exception:
            pass

    # 为每个直播场次匹配最佳市场
    for game in games:
        cache_key  = f"{game['blue']['name']}|{game['red']['name']}"
        best_match = None
        best_score = 0.0

        for ev in all_events:
            title = ev.get("title", "")
            if " vs " not in title.lower():
                if any(kw in title.lower() for kw in EXCLUDE_KW):
                    continue

            for m in ev.get("markets", []):
                if not m.get("active") or m.get("closed"):
                    continue
                try:
                    outcomes = json.loads(m.get("outcomes", "[]"))
                    prices   = [float(p) for p in json.loads(m.get("outcomePrices", "[]"))]
                    volume   = float(m.get("volume", 0) or 0)
                    if len(outcomes) != 2 or len(prices) != 2:
                        continue
                    out_set = {o.lower() for o in outcomes}
                    if out_set in [{"yes", "no"}, {"over", "under"}, {"odd", "even"}]:
                        continue
                    if volume < 200:
                        continue

                    s0b = _sim(outcomes[0], game["blue"]["name"])
                    s0r = _sim(outcomes[0], game["red"]["name"])
                    s1b = _sim(outcomes[1], game["blue"]["name"])
                    s1r = _sim(outcomes[1], game["red"]["name"])
                    score_ab = (s0b + s1r) / 2
                    score_ba = (s0r + s1b) / 2
                    best_this = max(score_ab, score_ba)

                    if best_this > best_score and best_this > 0.50:
                        best_score = best_this
                        if score_ab >= score_ba:
                            best_match = {
                                "blue_price": prices[0], "red_price": prices[1],
                                "volume": volume, "question": m.get("question", ""),
                            }
                        else:
                            best_match = {
                                "blue_price": prices[1], "red_price": prices[0],
                                "volume": volume, "question": m.get("question", ""),
                            }
                except Exception:
                    continue

        _poly_cache[cache_key] = best_match

    _poly_last_refresh = time.time()


def get_cached_poly(game: dict) -> dict | None:
    cache_key = f"{game['blue']['name']}|{game['red']['name']}"
    return _poly_cache.get(cache_key)

# ══════════════════════════════════════════════════════════════════
# 信号评估（纯战局触发，Polymarket 仅参考）
# ══════════════════════════════════════════════════════════════════

def _poly_hint(price: float | None) -> str:
    """
    根据 Polymarket 当前价格，给出入场时机提示。
    价格越高，说明 Poly 越「未更新」，机会窗口越大。
    """
    if price is None:
        return "Poly:?¢ (未找到市场)"
    pct = round(price * 100, 1)
    if price >= 0.45:
        return f"Poly:{pct}¢ ⚡未更新→速买"    # Poly 还没动，最佳入场时机
    elif price >= 0.25:
        return f"Poly:{pct}¢ 🔶部分更新"         # 已开始移动，窗口收窄
    elif price >= 0.08:
        return f"Poly:{pct}¢ 🔴已更新"           # Poly 已消化，核实后再决定
    else:
        return f"Poly:{pct}¢ (极低，彩票型)"


def evaluate_and_notify(game: dict, state: dict, poly: dict | None, now: float) -> None:
    """
    基于实时战局数据判断信号。

    ✅ 触发条件（只看战局）：
      - 游戏时间 >= MIN_GAME_MIN（避免开局噪音）
      - 金差 < GOLD_DIFF_MAX（落后但仍有翻盘可能）
      - 无抑制器被破（游戏尚未进入尾声）

    ℹ️ Polymarket 赔率仅作为参考信息显示在通知正文中，不作为触发条件。
    """
    game_id = game["game_id"]
    league  = game["league"]

    # 基础过滤（仅战局数据）
    if state["game_time_min"] < MIN_GAME_MIN:
        return
    if state["blue_inhibitors"] > 0 or state["red_inhibitors"] > 0:
        return  # 抑制器被破 = 游戏进入尾声，不是好的入场时机

    gold_diff = state["gold_diff"]  # 正 = 蓝方领先；负 = 红方领先

    # 检查蓝方落后 / 红方落后
    checks = [
        # (side,   team,         deficit,    ahead_drags,               poly_price_key)
        ("blue", game["blue"],  -gold_diff, state["red_dragons"],  poly.get("blue_price") if poly else None),
        ("red",  game["red"],    gold_diff, state["blue_dragons"], poly.get("red_price")  if poly else None),
    ]

    for side, team, deficit, ahead_dragons, poly_price in checks:
        if deficit <= 0:
            continue  # 这边领先，不看
        if deficit > GOLD_DIFF_MAX:
            continue  # 落后超过阈值

        ckey = (game_id, side)
        if now - _notified.get(ckey, 0) < NOTIFY_COOLDOWN:
            continue
        _notified[ckey] = now

        # 信号强度（基于金差）
        if deficit < 1000:
            strength, sound = "⭐⭐⭐ 极强", "Glass"
        elif deficit < 2000:
            strength, sound = "⭐⭐ 强",    "Ping"
        else:
            strength, sound = "⭐ 中",      "Tink"

        gmin       = state["game_time_min"]
        hint       = _poly_hint(poly_price)
        side_drags = state[f"{side}_dragons"]
        side_tower = state[f"{side}_towers"]

        title = f"🎯 {strength} · {league} · {team['code']} -{deficit:.0f}金"
        body  = (
            f"第{gmin:.0f}分 · {hint} · "
            f"龙{side_drags}个 · 塔{side_tower}座"
        )
        notify(title, body, sound)

# ══════════════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    notify(
        "LoL 实时监控 v2 已启动",
        f"战局触发（不等Poly价格）· LiveStats每{INTERVAL}s · Poly每{POLY_REFRESH}s刷新",
        "Glass",
    )
    print(f"[{datetime.now():%H:%M:%S}] 实时战局监控 v2 启动")
    print(f"  触发：游戏>{MIN_GAME_MIN}分 · 金差<{GOLD_DIFF_MAX} · 无抑制器（不过滤Poly价格）")
    print(f"  LiveStats 每 {INTERVAL}s · Polymarket 每 {POLY_REFRESH}s 刷新")
    print("-" * 60)

    while True:
        now  = time.time()
        ts   = datetime.now().strftime("%H:%M:%S")
        games = get_live_games()

        if not games:
            print(f"[{ts}] 暂无直播 LCK/LPL/LEC/LCS 场次")
        else:
            game_list = ", ".join(
                f"{g['blue']['code']} vs {g['red']['code']} ({g['league']})"
                for g in games
            )
            print(f"[{ts}] 直播中: {game_list}")

            # 检测新场次（game_id 首次出现时通知）
            for game in games:
                gid = game["game_id"]
                if gid not in _known_game_ids:
                    _known_game_ids.add(gid)
                    bw = game["blue_wins"]
                    rw = game["red_wins"]
                    notify(
                        f"🏆 新场次开始 · {game['league']}",
                        f"{game['blue']['code']}({bw}胜) vs {game['red']['code']}({rw}胜) · 监控已启动",
                        "Pop",
                    )

            # 独立刷新 Polymarket 缓存（节流，不影响战局轮询频率）
            if now - _poly_last_refresh > POLY_REFRESH:
                refresh_polymarket_cache(games)
                print(f"[{ts}] Polymarket 缓存刷新 ({len(games)} 场)")

        # 读取每场比赛的实时战况
        for game in games:
            state = get_game_state(game["game_id"])
            if not state:
                continue  # 204 局间等待或 API 错误，跳过

            # 打印当前战况
            gd     = state["gold_diff"]
            gd_str = f"+{gd}" if gd > 0 else str(gd)
            print(
                f"  └ {game['blue']['code']} "
                f"{state['blue_kills']}k/{state['blue_towers']}t/{state['blue_dragons']}d "
                f"| 金{gd_str} | "
                f"{game['red']['code']} "
                f"{state['red_kills']}k/{state['red_towers']}t/{state['red_dragons']}d  "
                f"~{state['game_time_min']:.0f}分"
            )

            poly = get_cached_poly(game)
            if poly:
                bp = round(poly["blue_price"] * 100, 1)
                rp = round(poly["red_price"]  * 100, 1)
                print(f"    Poly: {game['blue']['code']} {bp}¢ / {game['red']['code']} {rp}¢  vol:${poly['volume']:,.0f}")
            else:
                print(f"    Poly: 未找到匹配市场")

            evaluate_and_notify(game, state, poly, now)

        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[已停止]")
        notify("LoL 实时监控 v2", "已停止", "Basso")
