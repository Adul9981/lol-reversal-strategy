"""
Step 7: 分析每局小局的价格走势，识别游戏窗口和反转信号

输入:
  data/game_winner_markets/game_winner_markets.json
  data/game_winner_markets/game_price_history/{token_id}.json

输出:
  data/game_winner_markets/game_analysis_v2.json

关键逻辑:
  - 价格历史是10分钟一个点，市场在比赛前几天开放
  - 游戏结束: 价格稳定在 ≥0.95 或 ≤0.05（精度 ±10 分钟）
  - 游戏开始: 从结束时间向前找150分钟内第一个大幅价格变动（>0.05/点）
  - 核心指标使用 mins_before_end（比游戏分钟更可靠）
"""

import json
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).parent.parent
MARKETS_FILE = BASE / "data/game_winner_markets/game_winner_markets.json"
HIST_DIR = BASE / "data/game_winner_markets/game_price_history"
OUT_FILE = BASE / "data/game_winner_markets/game_analysis_v2.json"

SETTLE_THRESHOLD = 0.05   # price <= this or >= 1-this = settled
BIG_MOVE_THRESHOLD = 0.05  # price change in one 10-min step = in-game
MAX_GAME_LOOKBACK = 150    # max minutes to look back for game start


def find_game_end(history):
    """Find the first index where price is settled (>=0.95 or <=0.05).
    Returns (idx, is_winner_token0) or (None, None).
    """
    for i, pt in enumerate(history):
        p = pt["p"]
        if p >= (1 - SETTLE_THRESHOLD):
            return i, True   # token_0 won
        if p <= SETTLE_THRESHOLD:
            return i, False  # token_0 lost
    return None, None


def find_game_start(history, game_end_idx):
    """Look back up to MAX_GAME_LOOKBACK minutes from game_end_idx.
    Find the earliest point where a big move (>BIG_MOVE_THRESHOLD) occurred.
    Returns start_idx (inclusive) or None.
    """
    if game_end_idx < 2:
        return None

    game_end_t = history[game_end_idx]["t"]
    lookback_t = game_end_t - MAX_GAME_LOOKBACK * 60

    # collect points in window
    window = [
        i for i in range(game_end_idx)
        if history[i]["t"] >= lookback_t
    ]
    if not window:
        return None

    # scan forward: find first point where |delta_p| > threshold
    first_big = None
    for j in range(1, len(window)):
        idx = window[j]
        prev_idx = window[j - 1]
        dp = abs(history[idx]["p"] - history[prev_idx]["p"])
        if dp > BIG_MOVE_THRESHOLD:
            first_big = prev_idx  # game started before this move
            break

    return first_big if first_big is not None else window[0]


def analyze_token(token_id, market_meta):
    hist_file = HIST_DIR / f"{token_id}.json"
    if not hist_file.exists():
        return None

    history = json.loads(hist_file.read_text())
    if len(history) < 3:
        return None

    game_end_idx, token0_won = find_game_end(history)
    if game_end_idx is None:
        return None

    game_end_t = history[game_end_idx]["t"]
    game_start_idx = find_game_start(history, game_end_idx)
    if game_start_idx is None:
        game_start_idx = 0

    game_start_t = history[game_start_idx]["t"]
    game_duration_mins = (game_end_t - game_start_t) / 60

    # In-game price sequence
    in_game = history[game_start_idx:game_end_idx]
    if not in_game:
        return None

    prices = [pt["p"] for pt in in_game]
    times  = [pt["t"] for pt in in_game]

    # Which team won?
    winner    = market_meta["outcome_0"] if token0_won else market_meta["outcome_1"]
    loser     = market_meta["outcome_1"] if token0_won else market_meta["outcome_0"]
    win_price = lambda p: p if token0_won else (1 - p)

    win_prices_in_game = [win_price(p) for p in prices]

    game_open_p = win_prices_in_game[0]
    win_min_p   = min(win_prices_in_game)
    win_max_p   = max(win_prices_in_game)
    win_final_p = win_price(history[game_end_idx - 1]["p"]) if game_end_idx > 0 else None

    # Timing of minimum
    min_idx_in_game = win_prices_in_game.index(win_min_p)
    min_t = times[min_idx_in_game]
    mins_before_end = (game_end_t - min_t) / 60
    # game minute of minimum (from game start)
    game_min_of_bottom = (min_t - game_start_t) / 60

    # Drop from game open to minimum
    drop = game_open_p - win_min_p  # positive = dropped
    drop_pct = drop / game_open_p if game_open_p > 0 else 0

    # loser_min_p = 1 - win_max_p (the loser's lowest price = 1 minus winner's highest)
    loser_min_p = round(1 - win_max_p, 4)

    # Timing of loser's minimum = timing of winner's maximum
    max_idx_in_game = win_prices_in_game.index(win_max_p)
    max_t = times[max_idx_in_game]
    loser_min_mins_before_end = (game_end_t - max_t) / 60
    loser_min_game_min = (max_t - game_start_t) / 60

    game_end_dt = datetime.fromtimestamp(game_end_t, tz=timezone.utc)

    return {
        "event_title":        market_meta["event_title"],
        "league":             market_meta["league"],
        "game_question":      market_meta["game_question"],
        "winner":             winner,
        "loser":              loser,
        "volume":             market_meta["volume"],
        # Prices
        "game_open_p":        round(game_open_p, 4),
        "win_min_p":          round(win_min_p, 4),
        "win_max_p":          round(win_max_p, 4),
        "loser_min_p":        loser_min_p,
        "win_final_p":        round(win_final_p, 4) if win_final_p else None,
        # Winner's minimum timing (reversal signal timing)
        "mins_before_end":            round(mins_before_end, 0),
        "game_min_of_bottom":         round(game_min_of_bottom, 0),
        # Loser's minimum timing (failure case timing)
        "loser_min_mins_before_end":  round(loser_min_mins_before_end, 0),
        "loser_min_game_min":         round(loser_min_game_min, 0),
        "game_duration_mins": round(game_duration_mins, 0),
        # Drop stats
        "drop_abs":           round(drop, 4),
        "drop_pct":           round(drop_pct, 4),
        # Metadata
        "game_date":          game_end_dt.strftime("%Y-%m-%d"),
        "game_time":          game_end_dt.strftime("%H:%M"),
        "n_pts_total":        len(history),
        "n_pts_in_game":      len(in_game),
        "token_0":            token_id,
    }


def main():
    with open(MARKETS_FILE) as f:
        markets = json.load(f)

    target_leagues = {"LCK", "LPL", "LEC", "LCS"}
    targets = [m for m in markets if m["league"] in target_leagues]
    print(f"Target markets: {len(targets)}")

    results = []
    skipped = 0
    for m in targets:
        rec = analyze_token(m["token_0"], m)
        if rec:
            results.append(rec)
        else:
            skipped += 1

    results.sort(key=lambda x: x["game_date"], reverse=True)

    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Analyzed: {len(results)} games, skipped: {skipped}")
    print()

    # ── Stats ────────────────────────────────────────────────
    print("=== Summary Stats ===")
    print(f"Total games analyzed: {len(results)}")

    # Reversal analysis: winner's min_p thresholds
    for thresh, label in [(0.30, "<30%"), (0.20, "<20%"), (0.10, "<10%")]:
        subset = [r for r in results if r["win_min_p"] < thresh]
        pct = len(subset)/len(results)*100 if results else 0
        print(f"  Winner min odds {label}: {len(subset)} ({pct:.1f}%)")

    print()
    # mins_before_end for reversal games
    reversal = [r for r in results if r["win_min_p"] < 0.30]
    if reversal:
        mins_vals = [r["mins_before_end"] for r in reversal]
        print(f"For games where winner dropped <30%:")
        print(f"  mins_before_end: avg={sum(mins_vals)/len(mins_vals):.0f}, "
              f"min={min(mins_vals):.0f}, max={max(mins_vals):.0f}")
        dur_vals = [r["game_duration_mins"] for r in reversal]
        print(f"  game_duration_mins: avg={sum(dur_vals)/len(dur_vals):.0f}")

    # Distribution of game durations
    print()
    print("Game duration distribution (all games):")
    dur_all = [r["game_duration_mins"] for r in results]
    for lo, hi in [(0,20),(20,40),(40,60),(60,80),(80,999)]:
        cnt = sum(1 for d in dur_all if lo <= d < hi)
        print(f"  {lo}-{hi} min: {cnt}")

    # League breakdown
    print()
    print("By league:")
    for league in ["LCK", "LPL", "LEC", "LCS"]:
        lg = [r for r in results if r["league"] == league]
        rev = [r for r in lg if r["win_min_p"] < 0.30]
        rate = len(rev)/len(lg)*100 if lg else 0
        print(f"  {league}: {len(lg)} games, {len(rev)} reversals ({rate:.1f}%)")


if __name__ == "__main__":
    main()
