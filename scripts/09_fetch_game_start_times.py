"""
Step 9: 获取每局游戏的精确开始时间

流程：
  1. 从 LoL Esports API 获取 LCK/LPL/LEC/LCS 所有比赛列表和 game ID
  2. 将 Polymarket 市场与 LoL 比赛按日期 + 队名模糊匹配
  3. 扫 livestats window 找到 totalGold==2500 帧 → 游戏 00:00

输出：
  data/game_winner_markets/game_start_times.json
  格式: { token_0: { "lol_game_id": ..., "game_start_ts": ..., "game_start_iso": ... } }
"""

import json, time, math
import requests, urllib3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

urllib3.disable_warnings()

BASE      = Path(__file__).parent.parent
ANALYSIS  = BASE / "data/game_winner_markets/game_analysis_v2.json"
OUT_FILE  = BASE / "data/game_winner_markets/game_start_times.json"

API_KEY   = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
LEAGUE_IDS = {
    "LCK": "98767991310872058",
    "LPL": "98767991314006698",
    "LEC": "98767991302996019",
    "LCS": "98767991299243165",
}

s = requests.Session()
s.verify = False
s.headers["x-api-key"] = API_KEY


# ── 1. Fetch LoL API schedule ───────────────────────────────────────────────

def fetch_schedule(league_id):
    """Fetch all schedule events for a league (paginated)."""
    events = []
    page_token = None
    for _ in range(20):
        params = {"hl": "en-US", "leagueId": league_id}
        if page_token:
            params["pageToken"] = page_token
        r = s.get("https://esports-api.lolesports.com/persisted/gw/getSchedule",
                  params=params, timeout=15)
        if r.status_code != 200:
            break
        d = r.json()["data"]["schedule"]
        ev = d.get("events", [])
        events.extend(ev)
        page_token = d.get("pages", {}).get("newer")
        if not page_token or not ev:
            break
    return events


def fetch_event_games(match_id):
    """Return list of {number, id} for games in a match."""
    r = s.get("https://esports-api.lolesports.com/persisted/gw/getEventDetails",
              params={"hl": "en-US", "id": match_id}, timeout=15)
    if r.status_code != 200:
        return []
    event = r.json().get("data", {}).get("event", {})
    return event.get("match", {}).get("games", [])


# ── 2. Find game start via livestats ───────────────────────────────────────

def _probe(game_id: str, ts_str: str):
    """Single livestats probe with retry. Returns (has_data, gold, frame) or (False, 0, None)."""
    for attempt in range(3):
        try:
            r = s.get(f"https://feed.lolesports.com/livestats/v1/window/{game_id}",
                      params={"startingTime": ts_str}, timeout=12)
            if r.status_code == 200:
                frames = r.json().get("frames", [])
                if frames:
                    gold = frames[0].get("blueTeam", {}).get("totalGold", 0)
                    return True, gold, frames[0]
            return False, 0, None
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return False, 0, None


def find_game_start(game_id, game_end_ts: int):
    """
    Binary search + fine scan to find game 00:00 (totalGold≈2500).
    Uses ~8 probes instead of ~30, running ~4x faster.
    Returns unix timestamp (int) or None.
    """
    base = datetime.fromtimestamp(game_end_ts, tz=timezone.utc)

    # Binary search in [-100, -5] min range to find earliest window with data
    lo, hi = -100, -5
    while hi - lo > 5:
        mid = (lo + hi) // 2
        t = base + timedelta(minutes=mid)
        has_data, _, _ = _probe(game_id, t.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        time.sleep(0.08)
        if has_data:
            hi = mid   # data exists here; search earlier
        else:
            lo = mid   # no data; search later

    # hi is now approximately where data starts; fine scan from hi-3 to hi+8
    earliest_offset = None
    for offset in range(hi - 3, hi + 10):
        t = base + timedelta(minutes=offset)
        has_data, gold, f0 = _probe(game_id, t.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        time.sleep(0.08)
        if has_data:
            earliest_offset = offset
            # Check for totalGold ≈ 2500
            cs0 = (f0.get("blueTeam", {}).get("participants") or [{}])[0].get("creepScore", 0)
            if 2490 <= gold <= 2650 and cs0 == 0:
                ts_game = f0.get("rfc460Timestamp", "")
                if ts_game:
                    dt = datetime.fromisoformat(ts_game.replace("Z", "+00:00"))
                    return int(dt.timestamp())
            # Try the next minute too (gold may cross 2500 between minutes)
        elif earliest_offset is not None:
            break

    if earliest_offset is not None:
        return int((base + timedelta(minutes=earliest_offset)).timestamp())
    return None


# ── 3. Team name fuzzy matching ─────────────────────────────────────────────

def name_sim(a: str, b: str) -> float:
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return 1.0
    # Abbreviation match (code like T1, GEN, etc.)
    if len(a) <= 4 or len(b) <= 4:
        if a in b or b in a:
            return 0.85
    return SequenceMatcher(None, a, b).ratio()


def match_teams(pm_winner: str, pm_loser: str, lol_teams: list) -> float:
    """Return best similarity score for matching a Polymarket pair to a LoL team list."""
    if len(lol_teams) < 2:
        return 0.0
    a, b = lol_teams[0], lol_teams[1]
    # Try both orderings
    score1 = (name_sim(pm_winner, a) + name_sim(pm_loser, b)) / 2
    score2 = (name_sim(pm_winner, b) + name_sim(pm_loser, a)) / 2
    return max(score1, score2)


# ── 4. Main ──────────────────────────────────────────────────────────────────

def main():
    # Load existing results for resume
    if OUT_FILE.exists():
        results = json.loads(OUT_FILE.read_text())
    else:
        results = {}

    pm_games = json.loads(ANALYSIS.read_text())
    print(f"Polymarket games: {len(pm_games)}")
    print(f"Already resolved: {len(results)}")

    # ── Step 1: Build LoL API match database ─────────────────────────────
    print("\nFetching LoL API schedules...")
    lol_matches = []  # list of {date, match_id, teams, startTime_ts, league}
    for league, lid in LEAGUE_IDS.items():
        events = fetch_schedule(lid)
        for ev in events:
            st = ev.get("startTime", "")
            if st < "2026-04-01" or st > "2026-06-01":
                continue
            if ev.get("type") != "match":
                continue
            teams = [t["name"] for t in ev.get("match", {}).get("teams", [])]
            dt_st = datetime.fromisoformat(st.replace("Z", "+00:00"))
            lol_matches.append({
                "match_id":   ev["match"]["id"],
                "startTime":  st,
                "startTime_ts": int(dt_st.timestamp()),
                "date":       st[:10],
                "teams":      teams,
                "league":     league,
            })
        print(f"  {league}: {sum(1 for m in lol_matches if m['league']==league)} matches")

    print(f"Total LoL matches: {len(lol_matches)}")

    # ── Step 2: Pre-fetch game IDs for all matches ─────────────────────────
    print("\nFetching game IDs for each match...")
    match_games = {}  # match_id → list of {number, id}
    for i, m in enumerate(lol_matches):
        mid = m["match_id"]
        if mid in match_games:
            continue
        games = fetch_event_games(mid)
        match_games[mid] = games
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(lol_matches)}]")
        time.sleep(0.15)

    # ── Step 3: Match Polymarket → LoL, then scan for game start ──────────
    print(f"\nMatching and scanning game start times...")
    total    = len(pm_games)
    done     = 0
    skipped  = 0
    failed   = 0

    for pm in pm_games:
        token = pm["token_0"]
        if token in results:
            done += 1
            continue

        # Extract game number
        import re
        m = re.search(r"Game (\d+)", pm.get("game_question", ""), re.I)
        if not m:
            skipped += 1
            continue
        game_num = int(m.group(1))

        pm_date    = pm["game_date"]  # YYYY-MM-DD (game end date in UTC)
        pm_winner  = pm["winner"]
        pm_loser   = pm["loser"]
        # Game end timestamp from mins_before_end + game_duration
        # Better: reconstruct from settlement in price history
        # Approximate: game_date + game_time give UTC end time
        game_end_iso = f"{pm['game_date']}T{pm['game_time']}:00+00:00"
        game_end_ts  = int(datetime.fromisoformat(game_end_iso).timestamp())
        # Match day: end time minus duration ≈ start day
        approx_start_day = (datetime.fromtimestamp(game_end_ts, tz=timezone.utc)
                            - timedelta(hours=3)).strftime("%Y-%m-%d")

        # Find best matching LoL match
        best_match = None
        best_score = 0.0
        for lm in lol_matches:
            if lm["date"] not in (approx_start_day, pm_date):
                # Allow ±1 day
                lm_dt = datetime.fromisoformat(lm["date"])
                pm_dt = datetime.fromisoformat(pm_date)
                if abs((lm_dt - pm_dt).days) > 1:
                    continue
            score = match_teams(pm_winner, pm_loser, lm["teams"])
            if score > best_score:
                best_score = score
                best_match = lm

        if best_score < 0.55 or best_match is None:
            results[token] = {"error": f"no_match (best={best_score:.2f})"}
            failed += 1
            _save(results)
            continue

        # Get game ID for this game number
        games_in_match = match_games.get(best_match["match_id"], [])
        game_entry = next((g for g in games_in_match if g.get("number") == game_num), None)
        if not game_entry:
            results[token] = {"error": f"game_num_{game_num}_not_found"}
            failed += 1
            _save(results)
            continue

        lol_game_id = game_entry["id"]

        try:
            # Use Polymarket game end time (from settlement) as anchor for search
            game_start_ts = find_game_start(lol_game_id, game_end_ts)
        except Exception as e:
            results[token] = {"error": f"exception:{e}"}
            failed += 1
            _save(results)
            continue

        if game_start_ts:
            game_start_iso = datetime.fromtimestamp(game_start_ts, tz=timezone.utc).isoformat()
            results[token] = {
                "lol_game_id":    lol_game_id,
                "lol_match_id":   best_match["match_id"],
                "match_score":    round(best_score, 3),
                "lol_teams":      best_match["teams"],
                "game_start_ts":  game_start_ts,
                "game_start_iso": game_start_iso,
            }
            done += 1
            print(f"  ✓ {pm_winner} vs {pm_loser} G{game_num} → {game_start_iso[:19]}"
                  f"  (score={best_score:.2f})")
        else:
            results[token] = {"error": "start_not_found"}
            failed += 1
            print(f"  ✗ {pm_winner} vs {pm_loser} G{game_num} — start not found")

        _save(results)
        time.sleep(0.2)

    print(f"\n完成: done={done} failed={failed} skipped={skipped}")
    print(f"Output: {OUT_FILE}")


def _save(results):
    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
