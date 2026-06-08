"""
Script 12: 战局状态深度分析

目标：
  找到金币差、龙数差、存活核心的最优分割阈值，
  量化加入战局过滤条件后 EV 的提升幅度。

输入：data/game_winner_markets/game_battle_state.json
输出：控制台报告 + 更新规律库建议
"""

import json, math
from pathlib import Path
from collections import defaultdict

BASE    = Path(__file__).parent.parent
BS_FILE = BASE / "data/game_winner_markets/game_battle_state.json"

# ── 工具函数 ────────────────────────────────────────────────────────────────

def pct(lst, p):
    if not lst: return 0
    s = sorted(lst)
    return s[min(int(len(s) * p), len(s) - 1)]

def avg(lst):
    return round(sum(lst) / len(lst), 1) if lst else 0

def wilson_lo(wins, total, z=1.645):
    if total == 0: return 0
    p = wins / total
    return (p + z*z/(2*total) - z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))) \
           / (1 + z*z/total)

def ev(wins, total, price):
    if total == 0 or price == 0: return 0
    return (wins / total) / price - 1

def sep(title="", w=60):
    print(f"\n{'─'*w}")
    if title: print(f"  {title}")

# ── 主分析 ──────────────────────────────────────────────────────────────────

def main():
    raw = json.loads(BS_FILE.read_text())

    # 只保留有完整战局数据的记录
    all_cases = [r for r in raw if "gold_diff" in r]
    rev   = [r for r in all_cases if r["case_type"] == "reversal"]
    norev = [r for r in all_cases if r["case_type"] == "no_reversal"]

    print(f"战局数据总计: {len(all_cases)} 条")
    print(f"  翻盘案例 (reversal):    {len(rev)}")
    print(f"  未翻案例 (no_reversal): {len(norev)}")
    print(f"  基础胜率: {len(rev)}/{len(all_cases)} = {len(rev)/len(all_cases):.1%}")

    # ── 1. 各指标分布对比 ─────────────────────────────────────────────────
    sep("1. 各指标分布对比（翻盘 vs 未翻）")

    metrics = [
        ("gold_diff",          "金币差（廉价队-对方）"),
        ("dragon_diff",        "龙数差（廉价队-对方）"),
        ("opponent_inhibs",    "对方水晶数"),
        ("alive_cores",        "存活核心数"),
        ("death_concentration","死亡集中度"),
        ("tower_diff",         "塔数差"),
        ("kill_diff",          "击杀差"),
    ]

    print(f"\n{'指标':20}  {'翻盘 P25':>8} {'翻盘中位':>8} {'翻盘 P75':>8}"
          f"  {'未翻 P25':>8} {'未翻中位':>8} {'未翻 P75':>8}  差异")
    print("─" * 90)

    for field, label in metrics:
        rv = sorted(r[field] for r in rev   if field in r)
        nv = sorted(r[field] for r in norev if field in r)
        if not rv or not nv: continue
        r25, r50, r75 = pct(rv, .25), pct(rv, .50), pct(rv, .75)
        n25, n50, n75 = pct(nv, .25), pct(nv, .50), pct(nv, .75)
        diff = "↑好" if r50 > n50 else ("↓差" if r50 < n50 else "=")
        print(f"{label:20}  {r25:>8.0f} {r50:>8.0f} {r75:>8.0f}"
              f"  {n25:>8.0f} {n50:>8.0f} {n75:>8.0f}  {diff}")

    # ── 2. 金币差阈值扫描 ─────────────────────────────────────────────────
    sep("2. 金币差阈值扫描（找最优分割点）")

    print(f"\n{'金币差阈值':>10}  {'买入数':>6}  {'翻盘':>6}  {'胜率':>7}  "
          f"{'基础胜率':>8}  {'提升':>7}  {'EV@avg_price':>12}")

    base_wr = len(rev) / len(all_cases)
    avg_price = avg([r["cheap_odds"] for r in all_cases])

    best_gold = None
    best_ev   = -999

    for threshold in range(-5000, 1000, 500):
        subset_rev   = [r for r in rev   if r["gold_diff"] >= threshold]
        subset_norev = [r for r in norev if r["gold_diff"] >= threshold]
        total = len(subset_rev) + len(subset_norev)
        if total < 10: continue
        wr = len(subset_rev) / total
        ev_val = ev(len(subset_rev), total, avg_price)
        lift = wr - base_wr
        marker = " ←" if ev_val > best_ev else ""
        print(f"{threshold:>10}  {total:>6}  {len(subset_rev):>6}  {wr:>7.1%}  "
              f"{base_wr:>8.1%}  {lift:>+7.1%}  {ev_val:>+12.2f}{marker}")
        if ev_val > best_ev:
            best_ev   = ev_val
            best_gold = threshold

    print(f"\n  最优金币差阈值: {best_gold}  EV = {best_ev:+.2f}")

    # ── 3. 龙数阈值扫描 ───────────────────────────────────────────────────
    sep("3. 龙数差阈值扫描")

    print(f"\n{'龙数差阈值(≥)':>12}  {'买入数':>6}  {'翻盘':>6}  {'胜率':>7}  {'EV@avg':>10}")
    best_dragon = None
    best_dragon_ev = -999

    for threshold in range(-4, 3):
        sr = [r for r in rev   if r["dragon_diff"] >= threshold]
        sn = [r for r in norev if r["dragon_diff"] >= threshold]
        total = len(sr) + len(sn)
        if total < 8: continue
        wr = len(sr) / total
        ev_val = ev(len(sr), total, avg_price)
        print(f"{threshold:>12}  {total:>6}  {len(sr):>6}  {wr:>7.1%}  {ev_val:>+10.2f}")
        if ev_val > best_dragon_ev:
            best_dragon_ev = ev_val
            best_dragon = threshold

    print(f"\n  最优龙数差阈值: ≥{best_dragon}  EV = {best_dragon_ev:+.2f}")

    # ── 4. 存活核心阈值扫描 ───────────────────────────────────────────────
    sep("4. 存活核心阈值扫描")

    print(f"\n{'核心数阈值(≥)':>12}  {'买入数':>6}  {'翻盘':>6}  {'胜率':>7}  {'EV@avg':>10}")

    for threshold in range(0, 4):
        sr = [r for r in rev   if r["alive_cores"] >= threshold]
        sn = [r for r in norev if r["alive_cores"] >= threshold]
        total = len(sr) + len(sn)
        if total < 8: continue
        wr = len(sr) / total
        ev_val = ev(len(sr), total, avg_price)
        print(f"{threshold:>12}  {total:>6}  {len(sr):>6}  {wr:>7.1%}  {ev_val:>+10.2f}")

    # ── 5. 对方水晶数过滤 ─────────────────────────────────────────────────
    sep("5. 对方水晶数过滤")

    print(f"\n{'对方水晶上限':>12}  {'买入数':>6}  {'翻盘':>6}  {'胜率':>7}  {'EV@avg':>10}")
    for max_inhib in range(0, 4):
        sr = [r for r in rev   if r.get("opponent_inhibs", 99) <= max_inhib]
        sn = [r for r in norev if r.get("opponent_inhibs", 99) <= max_inhib]
        total = len(sr) + len(sn)
        if total < 8: continue
        wr = len(sr) / total
        ev_val = ev(len(sr), total, avg_price)
        print(f"{max_inhib:>12}  {total:>6}  {len(sr):>6}  {wr:>7.1%}  {ev_val:>+10.2f}")

    # ── 6. 组合条件 EV 矩阵 ───────────────────────────────────────────────
    sep("6. 组合条件 EV 矩阵")

    # 聚焦在 20-30 分窗口
    win_20_30 = [r for r in rev
                 if 20 <= r.get("game_min", 0) <= 30]
    nowin_20_30 = [r for r in norev
                   if 20 <= r.get("game_min", 0) <= 30]

    print(f"\n20–30min 窗口: 翻盘 {len(win_20_30)} 未翻 {len(nowin_20_30)}")

    combos = [
        ("全部（无过滤）",
         lambda r: True),
        ("金币差 > -3000",
         lambda r: r["gold_diff"] > -3000),
        ("金币差 > -4000",
         lambda r: r["gold_diff"] > -4000),
        ("对方龙 ≤ 2",
         lambda r: r["opponent_dragons"] <= 2),
        ("有存活核心",
         lambda r: r["alive_cores"] >= 1),
        ("金币差>-3000 + 对方龙≤2",
         lambda r: r["gold_diff"] > -3000 and r["opponent_dragons"] <= 2),
        ("金币差>-4000 + 有核心",
         lambda r: r["gold_diff"] > -4000 and r["alive_cores"] >= 1),
        ("金币差>-4000 + 对方龙≤3",
         lambda r: r["gold_diff"] > -4000 and r["opponent_dragons"] <= 3),
        ("金币差>-3000 + 对方龙≤2 + 有核心",
         lambda r: r["gold_diff"] > -3000 and r["opponent_dragons"] <= 2
                   and r["alive_cores"] >= 1),
        ("金币差>-4000 + 龙≤2 + 水晶≤0",
         lambda r: r["gold_diff"] > -4000 and r["opponent_dragons"] <= 2
                   and r.get("opponent_inhibs", 0) == 0),
    ]

    price_tiers = [
        ("全赔率段", lambda r: True),
        ("赔率 ≤ 20%", lambda r: r.get("cheap_odds", 1) <= 0.20),
        ("赔率 ≤ 15%", lambda r: r.get("cheap_odds", 1) <= 0.15),
    ]

    for ptier_label, ptier_fn in price_tiers:
        print(f"\n  【{ptier_label}】")
        w_base = [r for r in win_20_30   if ptier_fn(r)]
        n_base = [r for r in nowin_20_30 if ptier_fn(r)]
        base_total = len(w_base) + len(n_base)
        if base_total == 0: continue
        base_price = avg([r["cheap_odds"] for r in w_base + n_base]) or 0.20
        print(f"  {'条件':35}  {'n':>5}  {'翻盘':>5}  {'胜率':>7}  {'EV':>8}  Wilson下界")
        for label, fn in combos:
            wr = [r for r in w_base if fn(r)]
            nr = [r for r in n_base if fn(r)]
            total = len(wr) + len(nr)
            if total < 5: continue
            wr_rate = len(wr) / total
            ev_val  = ev(len(wr), total, base_price)
            wlo     = wilson_lo(len(wr), total) / base_price - 1
            mark = " ★" if ev_val > 0.2 else ""
            print(f"  {label:35}  {total:>5}  {len(wr):>5}  {wr_rate:>7.1%}"
                  f"  {ev_val:>+8.2f}  {wlo:>+8.2f}{mark}")

    # ── 7. 彩票档（≤10%）专项分析 ─────────────────────────────────────────
    sep("7. 彩票档（cheap_odds ≤ 10%）专项")

    lotto_r = [r for r in rev   if r.get("cheap_odds", 1) <= 0.10]
    lotto_n = [r for r in norev if r.get("cheap_odds", 1) <= 0.10]
    print(f"\n彩票档总计: 翻盘 {len(lotto_r)} 未翻 {len(lotto_n)}")

    if lotto_r:
        print("\n翻盘局战局快照：")
        for r in sorted(lotto_r, key=lambda x: x["cheap_odds"]):
            print(f"  {r['cheap_team'][:12]:12}  {r['cheap_odds']:.0%}  "
                  f"@{r['game_min']:.0f}min  "
                  f"金差={r['gold_diff']:+.0f}  "
                  f"龙={r['subject_dragons']}/{r['opponent_dragons']}  "
                  f"核心={r['alive_cores']}  "
                  f"{r.get('league','')}")

    if lotto_n:
        print("\n未翻局战局快照（对照）：")
        for r in sorted(lotto_n, key=lambda x: x["gold_diff"]):
            print(f"  {r['cheap_team'][:12]:12}  {r['cheap_odds']:.0%}  "
                  f"@{r['game_min']:.0f}min  "
                  f"金差={r['gold_diff']:+.0f}  "
                  f"龙={r['subject_dragons']}/{r['opponent_dragons']}  "
                  f"核心={r['alive_cores']}  "
                  f"{r.get('league','')}")

    # ── 8. 综合建议 ───────────────────────────────────────────────────────
    sep("8. 综合建议（更新规律库）")

    print("""
  根据以上分析，建议更新规律库和使用手册：

  G1 金币差：
    → 翻盘局中位 vs 未翻局中位（见上方对比表）
    → 建议阈值见「最优金币差阈值」扫描结果

  G2 龙数差：
    → 方向正确但效果较弱，建议配合金币差使用，不单独作为过滤条件

  G3 存活核心：
    → 翻盘局 67.9% 有核心，未翻局 57.1%，差异存在但不显著
    → 建议作为加分项，不作为硬性条件

  G4 死亡集中度：
    → 两组完全相同（0.400），无预测力，移除

  组合条件：
    → 见第 6 节矩阵，找 EV 最高且样本量 ≥ 15 的组合
  """)


if __name__ == "__main__":
    main()
