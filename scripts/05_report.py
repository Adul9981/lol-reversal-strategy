"""
Step 5: 汇总分析报告

整合 signals.jsonl + lolesports/ 数据，输出:
1. 基础逆转率 vs 信号命中率对比
2. 不同信号强度下的命中率（分位数分析）
3. 战局条件过滤后的命中率（金差、塔差、龙数）
4. 预期收益（EV）估算
"""

import json
from pathlib import Path
from statistics import mean, median

DATA_DIR      = Path(__file__).parent.parent / "data"
ALL_GAMES_FILE = DATA_DIR / "all_games.jsonl"
SIGNALS_FILE  = DATA_DIR / "signals.jsonl"
LOL_DIR       = DATA_DIR / "lolesports"
REPORT_FILE   = DATA_DIR / "report.md"


def load_jsonl(path):
    result = []
    with open(path) as f:
        for line in f:
            result.append(json.loads(line))
    return result


def win_rate(games, key="underdog_won"):
    wins = sum(1 for g in games if g.get(key) is True)
    total = sum(1 for g in games if g.get(key) is not None)
    return wins / total if total > 0 else 0, wins, total


def ev(win_rate, avg_odds):
    """期望收益: EV = win_rate * avg_odds - (1-win_rate)"""
    return win_rate * avg_odds - (1 - win_rate)


def main():
    print("=== Step 5: 生成分析报告 ===\n")

    # 加载数据
    all_games = load_jsonl(ALL_GAMES_FILE)
    signals   = load_jsonl(SIGNALS_FILE)

    total = len(all_games)
    with_signal = len(signals)

    # ── 1. 基础统计 ──────────────────────────────────────────
    base_rate, base_wins, base_total = win_rate(all_games)
    sig_rate, sig_wins, sig_total    = win_rate(signals)

    print(f"{'─'*55}")
    print(f"  【基础数据】")
    print(f"  总比赛场次:          {total:,}")
    print(f"  弱势方基础胜率:      {base_rate:.2%}  ({base_wins}/{base_total})")
    print(f"  ─────────────────────────────────────────────")
    print(f"  V型信号场次:         {with_signal:,} ({with_signal/total:.1%} 覆盖率)")
    print(f"  信号场次弱势方胜率:  {sig_rate:.2%}  ({sig_wins}/{sig_total})")
    if base_rate > 0:
        print(f"  信号提升倍数:        {sig_rate/base_rate:.2f}x")
    print(f"{'─'*55}\n")

    # ── 2. 按跌幅分位分析 ──────────────────────────────────
    print(f"  【按跌幅强度分层】")
    for threshold, label in [(0.25, "跌幅≥25%"), (0.35, "跌幅≥35%"),
                              (0.45, "跌幅≥45%"), (0.55, "跌幅≥55%")]:
        subset = []
        for game in signals:
            best_drop = max((s["drop_pct"] for s in game.get("signals", [])), default=0)
            if best_drop >= threshold:
                subset.append(game)
        if subset:
            r, w, t = win_rate(subset)
            print(f"  {label:12s}: {r:.2%}  ({w}/{t})")
    print()

    # ── 3. 按信号价格（弱势方赔率低点）分析 ─────────────────
    print(f"  【按弱势方赔率低点分层】")
    for max_price, label in [(0.15, "赔率<15%"), (0.20, "赔率<20%"),
                              (0.30, "赔率<30%"), (0.40, "赔率<40%")]:
        subset = []
        for game in signals:
            best_low = min((s["signal_price"] for s in game.get("signals", [])), default=1)
            if best_low < max_price:
                subset.append(game)
        if subset:
            r, w, t = win_rate(subset)
            print(f"  {label:12s}: {r:.2%}  ({w}/{t})")
    print()

    # ── 4. 战局条件过滤（如果有 LoL 数据）─────────────────
    lol_files = list(LOL_DIR.glob("*.json")) if LOL_DIR.exists() else []
    if lol_files:
        print(f"  【战局条件过滤 (n={len(lol_files)})】")
        lol_data = {}
        for fpath in lol_files:
            with open(fpath) as f:
                d = json.load(f)
            lol_data[d["event_id"]] = d

        # 建立索引: event_id -> signal game record
        sig_index = {g["event_id"]: g for g in signals}

        # 金差可控 (<3000)
        gold_ok = []
        for eid, lol in lol_data.items():
            game = sig_index.get(eid)
            if not game:
                continue
            for sig in lol.get("signals", []):
                gs = sig.get("game_state") or {}
                gold_diff = abs(gs.get("gold_diff", 99999))
                if gold_diff < 3000:
                    gold_ok.append(game)
                    break

        if gold_ok:
            r, w, t = win_rate(gold_ok)
            print(f"  金差<3000:           {r:.2%}  ({w}/{t})")

        # 弱势方持龙
        has_dragon = []
        for eid, lol in lol_data.items():
            game = sig_index.get(eid)
            if not game:
                continue
            for sig in lol.get("signals", []):
                gs = sig.get("game_state") or {}
                # 弱势方是underdog，判断蓝/红哪边是underdog需要额外信息
                # 简化：检查任意一方龙数>=1
                if gs.get("dragons_blue", 0) >= 1 or gs.get("dragons_red", 0) >= 1:
                    has_dragon.append(game)
                    break

        if has_dragon:
            r, w, t = win_rate(has_dragon)
            print(f"  持有小龙:            {r:.2%}  ({w}/{t})")
    else:
        print(f"  战局数据: 未拉取 (运行 04_fetch_lolesports.py 后查看)")

    print()

    # ── 5. EV 估算 ──────────────────────────────────────────
    print(f"  【期望收益 (EV) 估算】")
    print(f"  假设: 在信号触发时弱势方赔率约为 20-50x (赔率价格0.02~0.05)")
    for assumed_odds in [20, 30, 50, 80]:
        e = ev(sig_rate, assumed_odds)
        marker = " ✓" if e > 0 else " ✗"
        print(f"  赔率={assumed_odds:2d}x: EV={e:+.2f}{marker}")

    print()
    print(f"{'─'*55}")
    print(f"  结论: 信号命中率 {sig_rate:.1%} | 基础率 {base_rate:.1%} | 提升 {sig_rate/base_rate:.1f}x" if base_rate else "")

    # ── 6. 保存报告 ──────────────────────────────────────────
    report_lines = [
        "# LoL 反转信号回测报告",
        "",
        f"## 核心数据",
        f"- 总比赛场次: **{total:,}**",
        f"- 弱势方基础胜率: **{base_rate:.2%}** ({base_wins}/{base_total})",
        f"- V型信号场次: **{with_signal:,}** ({with_signal/total:.1%} 覆盖率)",
        f"- 信号场次弱势方胜率: **{sig_rate:.2%}** ({sig_wins}/{sig_total})",
        f"- 信号提升倍数: **{sig_rate/base_rate:.2f}x**" if base_rate else "",
        "",
        "## 信号参数",
        "- 跌幅阈值: ≥25%",
        "- 反弹阈值: ≥10%",
        "- 反弹持续: ≥5分钟",
        "",
        "## EV 估算 (按信号命中率)",
    ]
    for assumed_odds in [20, 30, 50]:
        e = ev(sig_rate, assumed_odds)
        report_lines.append(f"- 赔率{assumed_odds}x: EV = {e:+.2f}")

    REPORT_FILE.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n✓ 报告已保存到 {REPORT_FILE}")


if __name__ == "__main__":
    main()
