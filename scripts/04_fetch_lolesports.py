"""
Step 4: 从 LoL Esports API 拉取比赛实时战局数据

目标: 为有V型信号的场次，拉取对应的 LoL 游戏内数据
     （金币差、塔数、龙数）来验证信号时战局是否真的可翻盘

难点: Polymarket 事件只有队名+日期，需要匹配 LoL 游戏 ID

匹配策略:
1. 通过 LoL API getSchedule 按日期搜索比赛
2. 用队名做模糊匹配（去掉常见修饰词）
3. 匹配到 matchId 后，用 getEventDetails 获取 gameId
4. 用 getWindow API 拉取帧级别战局数据

输出: data/lolesports/{event_id}.json
"""

import json
import time
import requests
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

DATA_DIR      = Path(__file__).parent.parent / "data"
SIGNALS_FILE  = DATA_DIR / "signals.jsonl"
OUT_DIR       = DATA_DIR / "lolesports"

LOL_BASE   = "https://esports-api.lolesports.com/persisted/gw"
STATS_BASE = "https://feed.lolesports.com/livestats/v1"
API_KEY    = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
HEADERS    = {"x-api-key": API_KEY}

LEAGUE_IDS = [
    "98767991299243165",  # LCK
    "98767991302996019",  # LPL
    "98767991310872058",  # LEC
    "98767991314006698",  # LCS
    "104366452557571697", # PCS
    "107213827295848783", # VCS
    "98767991349978712",  # CBLOL
    "98767991335774713",  # LJL
]


def get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def normalize_team(name):
    """去掉常见修饰词，用于模糊匹配"""
    name = name.lower()
    # 去掉联赛前缀/后缀
    for word in ["esports", "gaming", "team", "academy", "challenger", "challengers",
                 "esport", "e-sports", "&", "the"]:
        name = re.sub(r'\b' + word + r'\b', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def team_similarity(a, b):
    na, nb = normalize_team(a), normalize_team(b)
    return SequenceMatcher(None, na, nb).ratio()


def find_match_in_schedule(team0, team1, date_str, league_ids=LEAGUE_IDS):
    """
    在 LoL 调度表中按日期和队名匹配比赛
    date_str 格式: "2026-05-22"
    """
    # 解析日期范围（±1天容差）
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    for league_id in league_ids:
        data = get(f"{LOL_BASE}/getSchedule",
                   params={"hl": "en-US", "leagueId": league_id})
        if not data:
            continue

        events = data.get("data", {}).get("schedule", {}).get("events", [])
        for evt in events:
            try:
                evt_time = datetime.fromisoformat(
                    evt["startTime"].replace("Z", "+00:00"))
                # 时间匹配：±1天
                if abs((evt_time - dt).total_seconds()) > 86400 * 2:
                    continue

                match = evt.get("match", {})
                teams = match.get("teams", [])
                if len(teams) < 2:
                    continue

                t0 = teams[0].get("name", "")
                t1 = teams[1].get("name", "")

                # 计算相似度 (双向匹配)
                sim_a = max(team_similarity(team0, t0), team_similarity(team0, t1))
                sim_b = max(team_similarity(team1, t0), team_similarity(team1, t1))

                if sim_a > 0.6 and sim_b > 0.6:
                    return {
                        "match_id":  match.get("id"),
                        "league_id": league_id,
                        "start_time": evt["startTime"],
                        "lol_team0": t0,
                        "lol_team1": t1,
                        "sim_a": round(sim_a, 3),
                        "sim_b": round(sim_b, 3),
                    }
            except Exception:
                continue
    return None


def get_game_ids(match_id):
    """从 matchId 获取 gameId 列表"""
    data = get(f"{LOL_BASE}/getEventDetails",
               params={"hl": "en-US", "id": match_id})
    if not data:
        return []
    games = data.get("data", {}).get("event", {}).get("match", {}).get("games", [])
    return [g["id"] for g in games if g.get("state") in ("completed", "inProgress", None)]


def get_window_at_time(game_id, signal_ts):
    """
    拉取信号时刻前后的战局快照
    LoL API 按 startingTime 返回该时间之后的帧数据
    """
    # 转换为 RFC3339
    dt = datetime.fromtimestamp(signal_ts - 300, tz=timezone.utc)  # 信号前5分钟
    start_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    data = get(f"{STATS_BASE}/window/{game_id}",
               params={"startingTime": start_str})
    if not data:
        return None

    frames = data.get("frames", [])
    if not frames:
        return None

    # 找最接近 signal_ts 的帧
    best_frame = None
    best_diff = float("inf")
    for frame in frames:
        try:
            ft = datetime.fromisoformat(
                frame["rfc460Timestamp"].replace("Z", "+00:00")).timestamp()
            diff = abs(ft - signal_ts)
            if diff < best_diff:
                best_diff = diff
                best_frame = frame
        except Exception:
            continue

    return best_frame


def extract_game_state(frame):
    """从帧数据提取关键战局指标"""
    if not frame:
        return {}

    teams = frame.get("blueTeam", {}), frame.get("redTeam", {})
    blue, red = teams

    return {
        "gold_blue":    blue.get("totalGold", 0),
        "gold_red":     red.get("totalGold", 0),
        "gold_diff":    blue.get("totalGold", 0) - red.get("totalGold", 0),
        "towers_blue":  blue.get("towers", 0),
        "towers_red":   red.get("towers", 0),
        "tower_diff":   blue.get("towers", 0) - red.get("towers", 0),
        "dragons_blue": blue.get("dragons", 0),
        "dragons_red":  red.get("dragons", 0),
        "barons_blue":  blue.get("barons", 0),
        "barons_red":   red.get("barons", 0),
        "kills_blue":   blue.get("kills", 0),
        "kills_red":    red.get("kills", 0),
    }


def process_signal_event(event):
    """为单个有信号的事件拉取 LoL 战局数据"""
    out_file = OUT_DIR / f"{event['event_id']}.json"
    if out_file.exists():
        return "skip"

    # 从 title 和 game_start_time 解析信息
    # title 格式: "LoL: Team A vs Team B" 或 "LoL: Team A vs Team B (BO5)"
    title = event.get("title", "")
    match_obj = re.search(r"LoL[:\s]+(.+?)\s+vs\s+(.+?)(?:\s+[\(\-]|$)", title, re.IGNORECASE)

    team0 = event.get("outcome_0", "")
    team1 = event.get("outcome_1", "")

    # 从 game_start_time 提取日期
    gst = event.get("game_start_time", "")
    date_str = gst[:10] if gst else event.get("end_date", "")[:10]

    if not (team0 and team1 and date_str):
        return "no_info"

    # 在 LoL API 中匹配比赛
    match_info = find_match_in_schedule(team0, team1, date_str)
    if not match_info:
        return "no_match"

    # 获取游戏 ID 列表
    game_ids = get_game_ids(match_info["match_id"])
    if not game_ids:
        return "no_games"

    # 为每个信号时刻拉取战局数据
    enriched_signals = []
    for sig in event.get("signals", []):
        sig_ts = sig["signal_ts"]
        game_state = None

        for gid in game_ids:
            frame = get_window_at_time(gid, sig_ts)
            if frame:
                game_state = extract_game_state(frame)
                game_state["game_id"] = gid
                break

        enriched_signals.append({**sig, "game_state": game_state})

    result = {
        "event_id":   event["event_id"],
        "title":      event["title"],
        "match_info": match_info,
        "game_ids":   game_ids,
        "signals":    enriched_signals,
        "team0_won":  event.get("team0_won"),
        "underdog_won": event.get("underdog_won"),
    }

    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return "ok"


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print("=== Step 4: LoL 战局数据匹配 ===")

    # 读取有信号的场次
    events = []
    with open(SIGNALS_FILE) as f:
        for line in f:
            events.append(json.loads(line))
    print(f"有V型信号的场次: {len(events)}")

    stats = {"ok": 0, "skip": 0, "no_match": 0, "no_games": 0, "no_info": 0, "error": 0}

    for i, event in enumerate(events, 1):
        try:
            result = process_signal_event(event)
            stats[result] = stats.get(result, 0) + 1
        except Exception as e:
            stats["error"] += 1
            if stats["error"] <= 3:
                print(f"  ✗ {event['event_id']}: {e}")
        time.sleep(0.2)

        if i % 20 == 0 or i == len(events):
            print(f"[{i:4d}/{len(events)}] {stats}")

    print(f"\n✓ 完成: {stats}")
    print(f"战局数据已保存到 {OUT_DIR}/")


if __name__ == "__main__":
    main()
