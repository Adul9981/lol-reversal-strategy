"""
Step 11: 获取触底时刻的战局快照

分析逻辑：
  将所有案例分为两类对比组：
    A) 翻盘案例 (reversal)  : winner 赔率曾跌至 <30%，触底在 15-40min，最终赢了
    B) 未翻案例 (no_reversal): loser  赔率曾跌至 <30%，触底在 15-40min，最终输了

  对每个案例，拉取「赔率触底那一分钟」的 Livestats 帧，
  从「廉价队」（cheap team）视角提取战局指标。

输出：
  data/game_winner_markets/game_battle_state.json
  格式: [ { case_type, token, cheap_team, gold_diff, ... }, ... ]
"""

import json, time
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

import requests, urllib3
urllib3.disable_warnings()

BASE       = Path(__file__).parent.parent
V3_FILE    = BASE / "data/game_winner_markets/game_analysis_v3.json"
TIMES_FILE = BASE / "data/game_winner_markets/game_start_times.json"
OUT_FILE   = BASE / "data/game_winner_markets/game_battle_state.json"

API_KEY    = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
THRESHOLD   = 0.30
MIN_BOT_MIN = 15
MAX_BOT_MIN = 40

s = requests.Session()
s.verify = False
s.headers["x-api-key"] = API_KEY


# ── 1. 预建 game_id → {blue_team, red_team} 映射 ───────────────────────────

def build_game_side_map(match_ids: list[str]) -> dict:
    """
    对每个 match_id 调用 getEventDetails，
    返回 {game_id: {blue_team: name, red_team: name}} 映射。
    """
    game_side = {}
    for i, mid in enumerate(match_ids):
        try:
            r = s.get(
                "https://esports-api.lolesports.com/persisted/gw/getEventDetails",
                params={"hl": "en-US", "id": mid}, timeout=15,
            )
            if r.status_code != 200:
                continue
            event = r.json().get("data", {}).get("event", {})
            match = event.get("match", {})
            # match 层面的队伍：有 id 和 name
            tid2name = {t["id"]: t["name"]
                        for t in match.get("teams", []) if "id" in t and "name" in t}
            # game 层面的队伍：有 id 和 side
            for game in match.get("games", []):
                gid = game.get("id", "")
                if not gid:
                    continue
                entry = {}
                for gt in game.get("teams", []):
                    side = gt.get("side", "")
                    name = tid2name.get(gt.get("id", ""), "")
                    if side in ("blue", "red") and name:
                        entry[side + "_team"] = name
                if entry:
                    game_side[gid] = entry
        except Exception as e:
            print(f"  [getEventDetails error] {mid}: {e}")
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(match_ids)}] game_side 条目: {len(game_side)}")
        time.sleep(0.15)
    return game_side


# ── 2. Livestats API ────────────────────────────────────────────────────────

def ts_str(unix_ts: int) -> str:
    """将 unix 时间戳整除 10 秒后格式化为 Livestats 接受的字符串。"""
    t = (unix_ts // 10) * 10
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_window(game_id: str, t: int):
    """拉取指定时间的 Livestats 窗口，返回解析后的 dict 或 None。"""
    for attempt in range(3):
        try:
            r = s.get(
                f"https://feed.lolesports.com/livestats/v1/window/{game_id}",
                params={"startingTime": ts_str(t)},
                timeout=12,
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


# ── 3. 提取战局指标 ─────────────────────────────────────────────────────────

def name_sim(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if a == b: return 1.0
    if a in b or b in a: return 0.85
    return SequenceMatcher(None, a, b).ratio()


def extract_metrics(window_data: dict, game_id: str,
                    subject_name: str, game_side_map: dict) -> dict | None:
    """
    以 subject_name（廉价队）为视角提取战局指标。
    gold_diff = subject_gold - opponent_gold（负数 = 廉价队处于金币劣势，正常现象）。
    """
    if not window_data:
        return None
    frames = window_data.get("frames", [])
    if not frames:
        return None

    frame    = frames[0]
    metadata = window_data.get("gameMetadata", {})

    # 确定廉价队在哪边（blue/red）
    sides = game_side_map.get(game_id, {})
    blue_name = sides.get("blue_team", "")
    red_name  = sides.get("red_team",  "")

    if blue_name and name_sim(subject_name, blue_name) >= 0.6:
        subj_side = "blue"
    elif red_name and name_sim(subject_name, red_name) >= 0.6:
        subj_side = "red"
    else:
        subj_side = None   # 无法匹配，不知道哪边

    blue = frame.get("blueTeam", {})
    red  = frame.get("redTeam",  {})

    if subj_side == "blue":
        s_t, o_t = blue, red
        s_meta = metadata.get("blueTeamMetadata", {}).get("participantsMetadata", [])
    elif subj_side == "red":
        s_t, o_t = red, blue
        s_meta = metadata.get("redTeamMetadata", {}).get("participantsMetadata", [])
    else:
        s_t, o_t = blue, red   # 默认蓝队，side_matched=False
        s_meta = metadata.get("blueTeamMetadata", {}).get("participantsMetadata", [])

    # 团队级 —— dragons 是列表，inhibitors/barons/towers 是整数
    def dragon_count(team): return len(team.get("dragons", []))

    s_drag = dragon_count(s_t)
    o_drag = dragon_count(o_t)
    s_gold = s_t.get("totalGold", 0)
    o_gold = o_t.get("totalGold", 0)

    # 个人级（廉价队 5 名选手）
    parts = s_t.get("participants", [])
    p_golds   = [p.get("totalGold",   0) for p in parts]
    p_deaths  = [p.get("deaths",      0) for p in parts]
    p_kills   = [p.get("kills",       0) for p in parts]
    p_assists = [p.get("assists",     0) for p in parts]
    p_cs      = [p.get("creepScore",  0) for p in parts]
    p_levels  = [p.get("level",       1) for p in parts]

    # 存活核心：死亡 ≤ 1 且击杀参与 ≥ 3
    alive_cores = sum(
        1 for k, d, a in zip(p_kills, p_deaths, p_assists)
        if d <= 1 and (k + a) >= 3
    )
    # 死亡集中度（越高 = 死亡越集中在一人身上）
    total_d = sum(p_deaths)
    death_conc = round(max(p_deaths) / total_d, 3) if total_d > 0 else 0.0

    # 冠军 ID
    champions = [m.get("championId", "") for m in s_meta] if s_meta else []

    return {
        "side_matched":       subj_side is not None,
        "subject_side":       subj_side or "unknown",
        "frame_ts":           frame.get("rfc460Timestamp", ""),
        # 团队级
        "gold_diff":          s_gold - o_gold,
        "subject_gold":       s_gold,
        "opponent_gold":      o_gold,
        "subject_dragons":    s_drag,
        "opponent_dragons":   o_drag,
        "dragon_diff":        s_drag - o_drag,
        "subject_dragon_types":  s_t.get("dragons", []),
        "opponent_dragon_types": o_t.get("dragons", []),
        "subject_barons":     s_t.get("barons",     0),
        "opponent_barons":    o_t.get("barons",     0),
        "subject_inhibs":     s_t.get("inhibitors", 0),
        "opponent_inhibs":    o_t.get("inhibitors", 0),
        "subject_towers":     s_t.get("towers",     0),
        "opponent_towers":    o_t.get("towers",     0),
        "tower_diff":         s_t.get("towers", 0) - o_t.get("towers", 0),
        "subject_kills":      s_t.get("totalKills", 0),
        "opponent_kills":     o_t.get("totalKills", 0),
        "kill_diff":          s_t.get("totalKills", 0) - o_t.get("totalKills", 0),
        # 个人级
        "player_golds":         p_golds,
        "player_deaths":        p_deaths,
        "player_kills":         p_kills,
        "player_cs":            p_cs,
        "player_levels":        p_levels,
        "max_player_gold":      max(p_golds)  if p_golds  else 0,
        "gold_spread":          (max(p_golds) - min(p_golds)) if len(p_golds) > 1 else 0,
        "total_deaths":         total_d,
        "death_concentration":  death_conc,
        "alive_cores":          alive_cores,
        "champions":            champions,
    }


# ── 4. Main ─────────────────────────────────────────────────────────────────

def main():
    # 断点续跑
    if OUT_FILE.exists():
        results = json.loads(OUT_FILE.read_text())
    else:
        results = []
    done_keys = {(r["token"], r["case_type"]) for r in results}

    v3    = json.loads(V3_FILE.read_text())
    times = json.loads(TIMES_FILE.read_text())

    precise = [r for r in v3
               if "accurate_game_min_of_bottom" in r and "game_start_ts" in r]
    print(f"有精确时间的局数: {len(precise)}")

    # 收集所有待处理案例
    cases_to_fetch = []
    for pm in precise:
        token = pm["token_0"]
        t_entry = times.get(token, {})
        if "error" in t_entry or not t_entry.get("lol_game_id"):
            continue
        game_id = t_entry["lol_game_id"]
        game_start = pm["game_start_ts"]
        winner, loser = pm["winner"], pm["loser"]

        # A: 翻盘案例
        if (pm.get("win_min_p", 1) < THRESHOLD
                and MIN_BOT_MIN <= pm.get("accurate_game_min_of_bottom", 0) <= MAX_BOT_MIN
                and (token, "reversal") not in done_keys):
            cases_to_fetch.append({
                "token": token, "game_id": game_id,
                "match_id": t_entry.get("lol_match_id", ""),
                "case_type": "reversal",
                "cheap_team": winner, "opponent_team": loser,
                "cheap_odds": pm["win_min_p"],
                "game_min":   pm["accurate_game_min_of_bottom"],
                "game_start": game_start,
                "league": pm.get("league", ""),
                "game_date": pm.get("game_date", ""),
            })

        # B: 未翻案例
        if (pm.get("loser_min_p", 1) < THRESHOLD
                and MIN_BOT_MIN <= pm.get("accurate_loser_min_game_min", 0) <= MAX_BOT_MIN
                and (token, "no_reversal") not in done_keys):
            cases_to_fetch.append({
                "token": token, "game_id": game_id,
                "match_id": t_entry.get("lol_match_id", ""),
                "case_type": "no_reversal",
                "cheap_team": loser, "opponent_team": winner,
                "cheap_odds": pm["loser_min_p"],
                "game_min":   pm["accurate_loser_min_game_min"],
                "game_start": game_start,
                "league": pm.get("league", ""),
                "game_date": pm.get("game_date", ""),
            })

    total = len(cases_to_fetch)
    rev_n   = sum(1 for c in cases_to_fetch if c["case_type"] == "reversal")
    norev_n = sum(1 for c in cases_to_fetch if c["case_type"] == "no_reversal")
    print(f"待拉取: {total}  (翻盘={rev_n} 未翻={norev_n})  已有: {len(done_keys)}")

    # 预建 game_side_map（只对涉及的 match_id）
    unique_mids = list({c["match_id"] for c in cases_to_fetch if c["match_id"]})
    print(f"\n构建 game_side_map（{len(unique_mids)} 场比赛）...")
    game_side_map = build_game_side_map(unique_mids)
    print(f"  game_side_map 覆盖 {len(game_side_map)} 个游戏\n")

    ok = fail = 0
    for i, case in enumerate(cases_to_fetch):
        t_bottom = case["game_start"] + int(case["game_min"] * 60)
        window   = fetch_window(case["game_id"], t_bottom)
        metrics  = extract_metrics(window, case["game_id"],
                                   case["cheap_team"], game_side_map)

        label = "翻" if case["case_type"] == "reversal" else "未"
        if metrics:
            tag = "✓" if metrics["side_matched"] else "?"
            print(f"  [{i+1:3d}/{total}] {tag}{label} "
                  f"{case['cheap_team'][:10]:10} vs {case['opponent_team'][:10]:10}"
                  f"  @{case['game_min']:.0f}min  {case['cheap_odds']:.0%}"
                  f"  金差={metrics['gold_diff']:+6.0f}"
                  f"  龙={metrics['subject_dragons']}/{metrics['opponent_dragons']}"
                  f"  核心={metrics['alive_cores']}"
                  f"  集中={metrics['death_concentration']:.2f}")
            results.append({**case, **metrics,
                            "t_bottom_iso": ts_str(t_bottom)})
            ok += 1
        else:
            print(f"  [{i+1:3d}/{total}] ✗{label} {case['cheap_team']} — 无数据")
            results.append({**case, "error": "no_data",
                            "t_bottom_iso": ts_str(t_bottom)})
            fail += 1

        _save(results)
        time.sleep(0.2)

    print(f"\n完成: ok={ok}  fail={fail}")
    _summarize(results)
    print(f"输出: {OUT_FILE}")


def _save(results: list):
    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))


def _summarize(results: list):
    rev   = [r for r in results if r.get("case_type") == "reversal"    and "gold_diff" in r]
    norev = [r for r in results if r.get("case_type") == "no_reversal" and "gold_diff" in r]
    if not rev or not norev:
        return
    def avg(lst): return round(sum(lst) / len(lst), 1)

    print("\n── 初步对比统计 ──")
    print(f"{'指标':28}  {'翻盘':>8}  {'未翻':>8}")
    print(f"{'样本数':28}  {len(rev):>8}  {len(norev):>8}")
    print(f"{'平均金币差':28}  {avg([r['gold_diff'] for r in rev]):>+8.0f}  "
          f"{avg([r['gold_diff'] for r in norev]):>+8.0f}")
    print(f"{'平均龙数差（己方-对方）':28}  {avg([r['dragon_diff'] for r in rev]):>+8.1f}  "
          f"{avg([r['dragon_diff'] for r in norev]):>+8.1f}")
    print(f"{'平均对方水晶数':28}  {avg([r['opponent_inhibs'] for r in rev]):>8.2f}  "
          f"{avg([r['opponent_inhibs'] for r in norev]):>8.2f}")
    print(f"{'平均击杀差':28}  {avg([r['kill_diff'] for r in rev]):>+8.1f}  "
          f"{avg([r['kill_diff'] for r in norev]):>+8.1f}")
    print(f"{'有存活核心(≥1)比例':28}  "
          f"{sum(1 for r in rev if r.get('alive_cores',0)>0)/len(rev):>8.1%}  "
          f"{sum(1 for r in norev if r.get('alive_cores',0)>0)/len(norev):>8.1%}")
    print(f"{'平均死亡集中度':28}  {avg([r['death_concentration'] for r in rev]):>8.3f}  "
          f"{avg([r['death_concentration'] for r in norev]):>8.3f}")


if __name__ == "__main__":
    main()
