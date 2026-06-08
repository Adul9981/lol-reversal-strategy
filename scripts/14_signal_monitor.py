#!/usr/bin/env python3
"""
Script 14 · LoL 策略信号监控 · macOS 通知版

监控 LCK / LPL / LEC / LCS 所有活跃市场。
发现 B型（热门临时低估）或 A型（弱势方逆风）信号时，
弹出 macOS 系统通知 + 打印日志。

运行:
  python3 scripts/14_signal_monitor.py

依赖:
  pip install requests      （已在 requirements_bot.txt 中）

不需要 API 密钥 / 私钥 / MetaMask — 只读取赔率，不下单。
"""

import json
import subprocess
import time
from datetime import datetime

import requests
import urllib3
urllib3.disable_warnings()

# ══════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════

INTERVAL        = 60     # 检查间隔（秒），每1分钟一次
NOTIFY_COOLDOWN = 300    # 同一市场 + 同一信号，5分钟内不重复提醒

# B型信号参数：热门方（上次检查 ≥70%）在本次检查跌入 58–82%，且跌幅 ≥8%
B_WAS_FAV   = 0.70   # 上次价格需 ≥ 此值才算"热门"
B_DROP_MIN  = 0.08   # 至少跌8个百分点
B_ZONE_LO   = 0.58   # 当前价格下限（低于此为A型范畴）
B_ZONE_HI   = 0.82   # 当前价格上限

# A型信号参数：弱势方当前赔率在 5–32%（LPL 跳过，信任度低）
A_LO  = 0.05
A_HI  = 0.32

# ══════════════════════════════════════════════════════════════════
# 运行时状态（内存，不持久化）
# ══════════════════════════════════════════════════════════════════

_prev_prices: dict[str, list[float]] = {}   # market_id → [p0, p1]
_notified:    dict[tuple, float]     = {}   # (market_id, signal_key) → 上次通知时间

# ══════════════════════════════════════════════════════════════════
# macOS 通知
# ══════════════════════════════════════════════════════════════════

def notify(title: str, body: str, sound: str = "Ping") -> None:
    """弹出 macOS 右上角系统通知"""
    # 清理引号避免 AppleScript 注入
    title = title.replace('"', "'")
    body  = body.replace('"', "'")
    script = f'display notification "{body}" with title "{title}" sound name "{sound}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] 🔔  {title}")
    print(f"         {body}")

# ══════════════════════════════════════════════════════════════════
# 联赛识别
# ══════════════════════════════════════════════════════════════════

def detect_league(title: str) -> str:
    t = title.upper()
    if "LCK"  in t: return "LCK"
    if "LPL"  in t: return "LPL"
    if "LEC"  in t or "EMEA" in t: return "LEC"
    if "LCS"  in t: return "LCS"
    return ""

# ══════════════════════════════════════════════════════════════════
# Polymarket Gamma API：获取活跃 LoL 市场
# ══════════════════════════════════════════════════════════════════

def fetch_active_markets() -> list[dict]:
    """
    返回所有活跃的 LoL 市场列表。
    同时抓取 league-of-legends 和 esports 两个标签，
    避免 LPL 比赛因标签不同而被漏掉。
    """
    # 两个标签都要查
    TAG_SLUGS = ["league-of-legends", "esports"]
    all_events: list[dict] = []
    seen_ids: set[str] = set()

    for tag in TAG_SLUGS:
        try:
            r = requests.get(
                "https://gamma-api.polymarket.com/events",
                params={
                    "active":   "true",
                    "closed":   "false",
                    "archived": "false",
                    "tag_slug": tag,
                    "limit":    100,
                },
                timeout=12,
            )
            r.raise_for_status()
            for ev in r.json():
                if ev.get("id") not in seen_ids:
                    seen_ids.add(ev.get("id"))
                    all_events.append(ev)
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] ⚠️  Gamma API ({tag}) 错误: {e}")

    events = all_events

    # 排除词：仅用于过滤「没有 vs 的赛季级/预测型」事件
    # ⚠️ 注意：不能对含 " vs " 的对战事件使用此过滤，
    #   否则会错误过滤 "LCK Road to MSI"（含msi）、"LPL Playoffs"（含playoff）等
    EXCLUDE_KEYWORDS = ["season", "winner", "champion", "challenger", "spring", "summer",
                        "split", "playoff", "worlds", "msi", "region"]

    markets = []
    for ev in events:
        league = detect_league(ev.get("title", ""))
        if not league:
            continue

        ev_title = ev.get("title", "").lower()
        # 只对非对战事件（不含 " vs "）才做关键词过滤
        # 含 " vs " 的事件是具体对战，不能过滤（即使包含 playoff/msi 等字样）
        if " vs " not in ev_title:
            if any(kw in ev_title for kw in EXCLUDE_KEYWORDS):
                continue

        for m in ev.get("markets", []):
            if not m.get("active") or m.get("closed"):
                continue
            try:
                outcomes = json.loads(m.get("outcomes", "[]"))
                prices   = [float(p) for p in json.loads(m.get("outcomePrices", "[]"))]
                if len(outcomes) != 2 or len(prices) != 2:
                    continue
                # 跳过非队伍对阵市场：Yes/No、Over/Under、Odd/Even
                outcome_set = set(o.lower() for o in outcomes)
                if outcome_set in [{"yes", "no"}, {"over", "under"}, {"odd", "even"}]:
                    continue
                # 跳过低成交量市场（噪声大，信号不可靠）
                volume = float(m.get("volume", 0) or 0)
                if volume < 500:
                    continue
                markets.append({
                    "id":          m["id"],
                    "league":      league,
                    "event_title": ev.get("title", ""),
                    "question":    m.get("question", ""),
                    "outcomes":    outcomes,
                    "prices":      prices,
                })
            except Exception:
                continue

    return markets

# ══════════════════════════════════════════════════════════════════
# 信号评估
# ══════════════════════════════════════════════════════════════════

def evaluate_signals(market: dict) -> list[dict]:
    """
    对单个市场评估 A型 / B型 信号。
    返回触发的信号列表（可能为空）。
    """
    mid      = market["id"]
    prices   = market["prices"]
    outcomes = market["outcomes"]
    league   = market["league"]
    prev     = _prev_prices.get(mid)
    signals  = []

    for i in range(2):
        p    = prices[i]
        name = outcomes[i]

        # ── B型：热门方临时低估 ─────────────────────────────
        # 需要有上次记录（冷启动时跳过）
        if prev is not None:
            p_prev = prev[i]
            drop   = p_prev - p
            if (
                p_prev >= B_WAS_FAV          # 上次是热门
                and drop >= B_DROP_MIN        # 跌幅足够
                and B_ZONE_LO <= p <= B_ZONE_HI  # 当前在B型区间
            ):
                signals.append({
                    "type":   "B",
                    "key":    f"B_{i}",
                    "team":   name,
                    "price":  p,
                    "p_prev": p_prev,
                    "drop":   drop,
                })

        # ── A型：弱势方逆风（LPL 跳过） ────────────────────
        if league != "LPL" and A_LO <= p <= A_HI:
            signals.append({
                "type":  "A",
                "key":   f"A_{i}",
                "team":  name,
                "price": p,
            })

    return signals

# ══════════════════════════════════════════════════════════════════
# 主循环
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    notify(
        "LoL 策略监控 已启动",
        f"监控 LCK / LPL / LEC / LCS · 每 {INTERVAL} 秒检查",
        "Glass",
    )
    print(f"[{datetime.now():%H:%M:%S}] 监控启动 — 间隔 {INTERVAL}s")
    print("  B型条件：上次≥70% → 本次跌入58-82%，且跌幅≥8%")
    print("  A型条件：当前赔率 5-32%（LCK/LEC/LCS，LPL跳过）")
    print("-" * 60)

    while True:
        markets = fetch_active_markets()
        now     = time.time()
        ts      = datetime.now().strftime("%H:%M:%S")

        if not markets:
            print(f"[{ts}] 无活跃 LoL 市场，下次 {INTERVAL} 秒后检查")
        else:
            print(f"[{ts}] 检查 {len(markets)} 个市场 "
                  f"({', '.join(sorted({m['league'] for m in markets}))})")

        for m in markets:
            mid     = m["id"]
            league  = m["league"]
            signals = evaluate_signals(m)

            for sig in signals:
                ckey = (mid, sig["key"])

                # 冷却检查
                if now - _notified.get(ckey, 0) < NOTIFY_COOLDOWN:
                    continue

                _notified[ckey] = now

                if sig["type"] == "B":
                    pct_now  = round(sig["price"]  * 100)
                    pct_prev = round(sig["p_prev"] * 100)
                    drop_pt  = round(sig["drop"]   * 100)
                    # 胜率参考（来自历史数据）
                    if pct_now >= 70:
                        wr_ref = "胜率~97%"
                    elif pct_now >= 60:
                        wr_ref = "胜率~81%"
                    else:
                        wr_ref = "胜率~71%"

                    title = f"⚡ B型 · {league} · {wr_ref}"
                    body  = (
                        f"{sig['team']} {pct_prev}¢→{pct_now}¢ (↓{drop_pt}pt) · "
                        f"{m['event_title'][:40]}"
                    )
                    notify(title, body, "Ping")

                elif sig["type"] == "A":
                    pct = round(sig["price"] * 100)
                    title = f"🔴 A型 · {league} · 弱势方{pct}¢"
                    body  = (
                        f"{sig['team']} 当前 {pct}¢ · "
                        f"{m['event_title'][:40]}"
                    )
                    notify(title, body, "Sosumi")

            # 更新历史价格
            _prev_prices[mid] = m["prices"]

        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[已停止]")
        notify("LoL 策略监控", "已停止", "Basso")
