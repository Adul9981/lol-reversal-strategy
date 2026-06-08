"""
Step 9: 期望收益（EV）分析

核心问题：当某队赔率跌至 X% 时入场押注，历史胜率和 EV 是多少？

分析逻辑（二元市场）：
  每场游戏中，对于阈值 T：
  - 成功案例：获胜方 win_min_p ≤ T（该队曾跌至 T% 然后赢了）
  - 失败案例：失败方 loser_min_p ≤ T（= 1 - win_max_p ≤ T，即失败方曾跌至 T% 然后输了）

  注意：由于 10分钟/点 的数据精度，一场游戏可能同时贡献多个阈值。

  EV 计算（假设以精确价格 T 入场）：
  EV = win_rate * (1/T) - 1  → 正数代表盈利

  更实际的 EV：考虑实际入场价（游戏内最低点附近）
"""

import json
from pathlib import Path

BASE = Path(__file__).parent.parent
ANALYSIS_FILE = BASE / "data/game_winner_markets/game_analysis_v2.json"

def main():
    data = json.loads(ANALYSIS_FILE.read_text())
    n = len(data)
    print(f"Total games: {n}\n")

    # ── 1. EV Table ─────────────────────────────────────────────
    print("=" * 72)
    print("  EV 分析：在赔率跌至 T% 时入场的期望收益")
    print("=" * 72)
    print(f"  {'阈值T':>6}  {'成功':>5}  {'失败':>5}  {'合计':>5}  {'胜率':>7}  {'EV(买T%)':>10}  {'EV(买T+5%)':>12}")
    print(f"  {'-'*6}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*7}  {'-'*10}  {'-'*12}")

    thresholds = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    ev_table = []
    for T in thresholds:
        # 成功：获胜方在游戏中曾跌至 ≤T
        success = sum(1 for r in data if r["win_min_p"] <= T)
        # 失败：失败方在游戏中曾跌至 ≤T（即获胜方曾升至 ≥1-T）
        failure = sum(1 for r in data if r["loser_min_p"] <= T)
        total = success + failure
        if total == 0:
            continue
        win_rate = success / total
        # EV if you buy exactly at T%
        ev_at_T = win_rate * (1/T) - 1 if T > 0 else 0
        # More realistic: buy at T+5% (slightly above the actual bottom)
        buy_price = T + 0.05
        ev_realistic = win_rate * (1/buy_price) - 1 if buy_price > 0 else 0

        ev_table.append({
            "T": T,
            "success": success,
            "failure": failure,
            "total": total,
            "win_rate": win_rate,
            "ev_at_T": ev_at_T,
            "ev_realistic": ev_realistic,
        })

        flag = "✓" if ev_at_T > 0 else "✗"
        print(f"  {T*100:>5.0f}%  {success:>5}  {failure:>5}  {total:>5}  {win_rate:>6.1%}  "
              f"{ev_at_T:>+9.2f}{flag}  {ev_realistic:>+11.2f}")

    print()

    # ── 2. Game Number Analysis ──────────────────────────────────
    print("=" * 60)
    print("  按局次分析（Game 1 vs Game 2 vs Game 3+）")
    print("=" * 60)
    for game_n, label in [("Game 1", "Game 1"), ("Game 2", "Game 2"),
                           ("Game 3", "Game 3"), ("Game 4", "Game 4"),
                           ("Game 5", "Game 5")]:
        subset = [r for r in data if game_n in r["game_question"]]
        if not subset:
            continue
        rev30 = [r for r in subset if r["win_min_p"] < 0.30]
        rev20 = [r for r in subset if r["win_min_p"] < 0.20]
        avg_vol = sum(r["volume"] for r in subset) / len(subset) if subset else 0
        print(f"  {label}: {len(subset):>3} 局  反转<30%: {len(rev30):>2} ({len(rev30)/len(subset)*100:4.1f}%)  "
              f"反转<20%: {len(rev20):>2} ({len(rev20)/len(subset)*100:4.1f}%)  "
              f"均交易量: ${avg_vol/1e3:.0f}K")

    print()

    # ── 3. Mins Before End Distribution for Reversals ────────────
    print("=" * 60)
    print("  触底时间分布（获胜方 min_p < 30% 的 56 局）")
    print("  （距游戏结束多少分钟时触底，±10分钟精度）")
    print("=" * 60)
    reversal = [r for r in data if r["win_min_p"] < 0.30]
    buckets = [(0,10),(10,20),(20,30),(30,40),(40,60)]
    for lo, hi in buckets:
        cnt = sum(1 for r in reversal if lo <= r["mins_before_end"] < hi)
        bar = "█" * cnt
        print(f"  {lo:>2}-{hi:<2} 分前: {cnt:>3}  {bar}")
    print()

    # ── 4. Detailed reversal cases ───────────────────────────────
    print("=" * 60)
    print("  最显著反转案例（获胜方 min_p < 15%）")
    print("=" * 60)
    extreme = [r for r in data if r["win_min_p"] < 0.15]
    extreme.sort(key=lambda r: r["win_min_p"])
    for r in extreme:
        game_n = ""
        import re
        m = re.search(r"Game (\d+)", r["game_question"])
        if m:
            game_n = f"G{m.group(1)}"
        print(f"  {r['game_date']} {r['league']:4s} {game_n}  "
              f"{r['winner']:20s} vs {r['loser']:20s}")
        print(f"           开局:{r['game_open_p']*100:.0f}%  "
              f"最低:{r['win_min_p']*100:.0f}%  "
              f"距结束:{r['mins_before_end']:.0f}分  "
              f"时长:{r['game_duration_mins']:.0f}分  "
              f"量:${r['volume']/1e3:.0f}K")
    print()

    # ── 5. Pre-game favorite vs underdog reversal rates ──────────
    print("=" * 60)
    print("  赛前弱势方（开局赔率<50%）vs 强势方 反转率对比")
    print("=" * 60)
    underdog = [r for r in data if r["game_open_p"] < 0.50]
    favorite = [r for r in data if r["game_open_p"] >= 0.50]
    print(f"  赛前弱势方（开局<50%）: {len(underdog)} 局")
    for T in [0.30, 0.20, 0.10]:
        rev = [r for r in underdog if r["win_min_p"] < T]
        print(f"    进一步下跌至<{T*100:.0f}%: {len(rev)} ({len(rev)/len(underdog)*100:.1f}%)")
    print(f"  赛前强势方（开局≥50%）: {len(favorite)} 局")
    for T in [0.30, 0.20, 0.10]:
        rev = [r for r in favorite if r["win_min_p"] < T]
        print(f"    下跌至<{T*100:.0f}%（大翻盘）: {len(rev)} ({len(rev)/len(favorite)*100:.1f}%)")


if __name__ == "__main__":
    main()
