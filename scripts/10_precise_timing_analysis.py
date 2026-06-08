"""
Step 10: 用精确游戏开始时间重新计算 EV 矩阵

输入:
  data/game_winner_markets/game_analysis_v2.json   — 每局分析（含价格历史统计）
  data/game_winner_markets/game_start_times.json   — LoL API 精确开始时间
  data/game_winner_markets/game_price_history/     — 原始价格历史

输出:
  data/game_winner_markets/game_analysis_v3.json   — 加入精确时间的完整分析
  (terminal) 精确 EV 矩阵 + 时间分布

关键变量:
  accurate_game_min_of_bottom  — 赢家触底时刻，游戏精确开始后第几分钟
  accurate_loser_min_game_min  — 输家触底时刻，游戏精确开始后第几分钟
"""

import json
from pathlib import Path
from datetime import datetime, timezone

BASE       = Path(__file__).parent.parent
ANALYSIS   = BASE / "data/game_winner_markets/game_analysis_v2.json"
START_FILE = BASE / "data/game_winner_markets/game_start_times.json"
HIST_DIR   = BASE / "data/game_winner_markets/game_price_history"
OUT_FILE   = BASE / "data/game_winner_markets/game_analysis_v3.json"

SETTLE_THRESHOLD = 0.05


def load_history(token_id):
    f = HIST_DIR / f"{token_id}.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())


def enrich_record(rec, start_ts: int) -> dict:
    """Add precise timing fields to an analysis record using accurate game start."""
    history = load_history(rec["token_0"])
    if not history:
        return rec

    # Find game end index (same logic as step 7)
    game_end_idx = None
    token0_won = None
    for i, pt in enumerate(history):
        p = pt["p"]
        if p >= (1 - SETTLE_THRESHOLD):
            game_end_idx = i
            token0_won = True
            break
        if p <= SETTLE_THRESHOLD:
            game_end_idx = i
            token0_won = False
            break
    if game_end_idx is None:
        return rec

    game_end_t = history[game_end_idx]["t"]

    # In-game prices: only points after game start and before settlement
    in_game = [pt for pt in history[:game_end_idx] if pt["t"] >= start_ts]
    if not in_game:
        # No price points fall within [start_ts, game_end_t] window
        # Use all points before settlement as fallback
        in_game = history[:game_end_idx]

    if not in_game:
        return rec

    win_price_fn = (lambda p: p) if token0_won else (lambda p: 1 - p)
    win_prices = [win_price_fn(pt["p"]) for pt in in_game]
    times      = [pt["t"] for pt in in_game]

    win_min_p  = min(win_prices)
    win_max_p  = max(win_prices)
    loser_min_p = round(1 - win_max_p, 4)

    # Timing of winner's minimum
    min_idx = win_prices.index(win_min_p)
    min_t   = times[min_idx]
    accurate_game_min_of_bottom       = (min_t - start_ts) / 60
    accurate_mins_before_end          = (game_end_t - min_t) / 60
    accurate_game_duration_mins       = (game_end_t - start_ts) / 60

    # Timing of loser's minimum (= winner's maximum)
    max_idx = win_prices.index(win_max_p)
    max_t   = times[max_idx]
    accurate_loser_min_game_min       = (max_t - start_ts) / 60
    accurate_loser_min_mins_before_end = (game_end_t - max_t) / 60

    enriched = dict(rec)
    enriched.update({
        # Overwrite with precise versions
        "win_min_p":                        round(win_min_p, 4),
        "win_max_p":                        round(win_max_p, 4),
        "loser_min_p":                      loser_min_p,
        "game_open_p":                      round(win_prices[0], 4),
        # Precise timing
        "accurate_game_min_of_bottom":      round(accurate_game_min_of_bottom, 1),
        "accurate_mins_before_end":         round(accurate_mins_before_end, 1),
        "accurate_game_duration_mins":      round(accurate_game_duration_mins, 1),
        "accurate_loser_min_game_min":      round(accurate_loser_min_game_min, 1),
        "accurate_loser_min_mins_before_end": round(accurate_loser_min_mins_before_end, 1),
        "game_start_ts":                    start_ts,
        "game_start_iso":                   datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
        "n_pts_in_game_precise":            len(in_game),
    })
    return enriched


def compute_ev_matrix(data):
    """Print EV matrix: buy threshold × minimum entry game minute."""
    thresholds  = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
    min_minutes = [0, 10, 15, 20, 25]

    print("=== 精确时间 EV 矩阵 ===")
    print("条件：触底发生在游戏开始后第 >= N 分钟")
    print(f"{'阈值':>6}  " + "  ".join(f"≥{m}分钟入场" for m in min_minutes))
    print("─" * 80)

    for T in thresholds:
        row = f"{int(T*100):5d}%  "
        for N in min_minutes:
            wins   = [r for r in data
                      if r.get("win_min_p", 1)   <= T
                      and r.get("accurate_game_min_of_bottom", 0) >= N]
            losses = [r for r in data
                      if r.get("loser_min_p", 1) <= T
                      and r.get("accurate_loser_min_game_min", 0) >= N]
            total  = len(wins) + len(losses)
            if total == 0:
                row += f"{'—':>12}  "
                continue
            wr  = len(wins) / total
            ev  = wr / T - 1
            sign = "+" if ev > 0 else ""
            row += f"WR{wr*100:.0f}%/{sign}{ev:.2f}(n={total})  "
        print(row)

    print()
    print("格式：WR胜率/EV(样本量)")


def print_timing_distribution(data):
    """Show distribution of reversal timing by game minute."""
    reversals = [r for r in data if r.get("win_min_p", 1) < 0.30
                 and "accurate_game_min_of_bottom" in r]

    if not reversals:
        print("No reversal records with precise timing yet.")
        return

    print(f"\n=== 反转局触底时刻分布（精确游戏分钟，<30% 反转，n={len(reversals)}）===")
    buckets = [(0,5),(5,10),(10,15),(15,20),(20,25),(25,30),(30,40),(40,999)]
    for lo, hi in buckets:
        cnt = sum(1 for r in reversals
                  if lo <= r["accurate_game_min_of_bottom"] < hi)
        bar = "█" * cnt
        label = f"{lo}-{hi if hi < 999 else '40+'}分钟"
        print(f"  {label:>12}:  {bar} {cnt}")

    mins = [r["accurate_game_min_of_bottom"] for r in reversals]
    print(f"\n  均值: {sum(mins)/len(mins):.1f}分钟  中位: {sorted(mins)[len(mins)//2]:.1f}分钟")
    durs = [r.get("accurate_game_duration_mins", 0) for r in reversals]
    print(f"  游戏均时长: {sum(durs)/len(durs):.1f}分钟")


def main():
    records    = json.loads(ANALYSIS.read_text())
    start_data = json.loads(START_FILE.read_text()) if START_FILE.exists() else {}

    print(f"Total games: {len(records)}")
    print(f"With precise start times: {sum(1 for v in start_data.values() if 'game_start_ts' in v)}")
    print()

    enriched = []
    no_start = 0
    for rec in records:
        token = rec["token_0"]
        st_entry = start_data.get(token, {})
        if "game_start_ts" in st_entry:
            enriched.append(enrich_record(rec, st_entry["game_start_ts"]))
        else:
            enriched.append(rec)   # keep original, no precise timing
            no_start += 1

    # Sort newest first
    enriched.sort(key=lambda x: x["game_date"], reverse=True)
    OUT_FILE.write_text(json.dumps(enriched, indent=2, ensure_ascii=False))
    print(f"Written: {OUT_FILE}  ({len(enriched)} records, {no_start} without precise timing)\n")

    # Only compute stats on records with precise timing
    precise = [r for r in enriched if "accurate_game_min_of_bottom" in r]
    print(f"Records with precise timing: {len(precise)}\n")

    if precise:
        compute_ev_matrix(precise)
        print_timing_distribution(precise)


if __name__ == "__main__":
    main()
