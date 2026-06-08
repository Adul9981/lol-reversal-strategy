"""
Step 3: V型信号检测 + 基础回测分析

对每场比赛的赔率历史执行以下逻辑:

1. 确定「比赛窗口」: game_start_time 之后的价格点
2. 在比赛窗口内找弱势方（落后方）的赔率走势
3. 检测V型结构:
   - 下跌阶段: 价格在N分钟内从高位下跌 > DROP_THRESHOLD
   - 反弹阶段: 价格从底部回升 > REBOUND_THRESHOLD，且持续 > MIN_REBOUND_MINS
4. 记录V型出现时的「信号时刻」及最终结果

输出:
  data/signals.jsonl   所有检测到V型信号的场次
  data/all_games.jsonl 所有分析过的场次（用于计算基础率）
"""

import json
import math
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR     = Path(__file__).parent.parent / "data"
HISTORY_DIR  = DATA_DIR / "price_history"
SIGNALS_FILE = DATA_DIR / "signals.jsonl"
ALL_GAMES_FILE = DATA_DIR / "all_games.jsonl"

# ── 信号参数（这些是待调参的阈值）──────────────────────────────
DROP_THRESHOLD    = 0.25   # 下跌幅度: 价格需从局部高点下跌>=25%
REBOUND_THRESHOLD = 0.10   # 反弹幅度: 从底部回升>=10%才算有效反弹
MIN_REBOUND_MINS  = 5      # 反弹需持续至少N分钟（即至少有N/10个数据点）
WINDOW_MINS_BEFORE_END = 10  # 排除比赛最后X分钟的信号（太晚了，赔率已锁定）
MIN_GAME_POINTS   = 3      # 比赛窗口内至少需要N个价格点

# 落后方定义: 赔率低于此值才检测V型（不要过高，避免对强势方建模）
UNDERDOG_THRESHOLD = 0.48
# ──────────────────────────────────────────────────────────────


def parse_ts(s):
    """将 game_start_time 字符串转成 Unix timestamp
    处理格式: '2026-05-22 09:00:00+00' / '2026-05-22T09:00:00Z' 等
    """
    if not s:
        return None
    import re
    s = s.strip()
    # 标准化:
    # "2026-05-22 09:00:00+00"  -> "2026-05-22 09:00:00+00:00"
    # "2026-05-22 09:00:00+0000"-> "2026-05-22 09:00:00+00:00"
    s = re.sub(r'([+-]\d{2})$', r'\1:00', s)     # +00 -> +00:00
    s = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', s)  # +0000 -> +00:00
    s = s.replace(' ', 'T')  # space -> T for fromisoformat
    s = s.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def detect_vsignal(history, game_start_ts, end_ts):
    """
    在比赛窗口内检测V型信号。
    返回 list of signal_info dicts，每个代表一个V型触发点。
    """
    if not history or game_start_ts is None:
        return []

    # 过滤出比赛窗口内的价格点（game_start 到 end - WINDOW_MINS_BEFORE_END）
    late_cutoff = (end_ts or float("inf")) - WINDOW_MINS_BEFORE_END * 60
    game_pts = [p for p in history
                if p["t"] >= game_start_ts and p["t"] <= late_cutoff]

    if len(game_pts) < MIN_GAME_POINTS:
        return []

    signals = []

    # 滑动窗口: 对每个点，向前看是否有足够的下跌，向后看是否有足够的反弹
    for i, pt in enumerate(game_pts):
        p_cur = pt["p"]

        # 只关注弱势方（赔率<UNDERDOG_THRESHOLD）
        if p_cur >= UNDERDOG_THRESHOLD:
            continue

        # === 下跌阶段: 寻找 i 之前的局部高点 ===
        # 向前找 high_point (最多看20个点 = 200分钟)
        lookback = game_pts[max(0, i-20): i]
        if not lookback:
            continue
        high_pt = max(lookback, key=lambda x: x["p"])
        high_p  = high_pt["p"]

        drop_pct = (high_p - p_cur) / high_p if high_p > 0 else 0
        if drop_pct < DROP_THRESHOLD:
            continue

        # === 反弹阶段: 从点i向后看 ===
        lookahead = game_pts[i+1:]
        if not lookahead:
            continue

        # 找从当前点开始的最大连续回升
        rebound_peak = p_cur
        rebound_end_ts = pt["t"]
        sustained = False

        for j, future_pt in enumerate(lookahead):
            rebound_pct = (future_pt["p"] - p_cur) / p_cur if p_cur > 0 else 0
            if rebound_pct >= REBOUND_THRESHOLD:
                # 检查持续时间
                duration_mins = (future_pt["t"] - pt["t"]) / 60
                if duration_mins >= MIN_REBOUND_MINS:
                    rebound_peak   = future_pt["p"]
                    rebound_end_ts = future_pt["t"]
                    sustained = True
                    break
            elif future_pt["p"] < p_cur * 0.95:
                # 价格继续下跌，不是V型，放弃
                break

        if not sustained:
            continue

        signals.append({
            "signal_ts":      pt["t"],
            "signal_price":   p_cur,
            "high_price":     high_p,
            "drop_pct":       round(drop_pct, 4),
            "rebound_price":  rebound_peak,
            "rebound_pct":    round((rebound_peak - p_cur) / p_cur, 4) if p_cur > 0 else 0,
            "rebound_end_ts": rebound_end_ts,
        })

    # 去重: 合并时间上相近的信号（60分钟内只保留最强的那个）
    if not signals:
        return []

    signals.sort(key=lambda x: x["signal_ts"])
    deduped = [signals[0]]
    for s in signals[1:]:
        if s["signal_ts"] - deduped[-1]["signal_ts"] > 3600:
            deduped.append(s)
        elif s["drop_pct"] > deduped[-1]["drop_pct"]:
            deduped[-1] = s

    return deduped


def analyze_file(filepath):
    """分析单个比赛文件，返回分析结果"""
    with open(filepath) as f:
        rec = json.load(f)

    history = rec.get("history", [])
    if not history:
        return None

    # 判断最终结果
    last_price_0 = rec.get("last_price_0")
    if last_price_0 is None:
        return None
    team0_won = last_price_0 > 0.5  # True = outcome_0 (team A) won

    # 整个历史中价格最低点（代表弱势方最惨时的赔率）
    prices = [p["p"] for p in history]
    min_price = min(prices)
    max_price = max(prices)

    # 比赛时间窗口
    game_start_ts = parse_ts(rec.get("game_start_time"))
    end_ts_str = rec.get("end_date", "")
    end_ts = parse_ts(end_ts_str.replace("Z", "+00:00") if end_ts_str else "")

    # 在比赛窗口内看弱势方
    underdog_won = None
    if game_start_ts:
        game_pts = [p for p in history if p["t"] >= game_start_ts]
        if game_pts:
            # 取比赛开始时的赔率
            start_price = game_pts[0]["p"]
            # 弱势方 = 赔率<0.5的那支队
            if start_price < 0.5:
                underdog_won = team0_won  # token_0 is underdog and they won?
            else:
                underdog_won = not team0_won

    # 检测V型信号
    # 我们需要从弱势方角度看V型
    # 如果team0是弱势方，直接用history
    # 如果team1是弱势方，用 1-p
    if game_start_ts:
        game_pts = [p for p in history if p["t"] >= game_start_ts]
        if game_pts and game_pts[0]["p"] > 0.5:
            # team0 is favored, invert prices to get underdog's view
            analysis_history = [{"t": p["t"], "p": 1 - p["p"]} for p in history]
        else:
            analysis_history = history
    else:
        analysis_history = history

    signals = detect_vsignal(analysis_history, game_start_ts, end_ts)

    base = {
        "event_id":     rec["event_id"],
        "title":        rec["title"],
        "outcome_0":    rec["outcome_0"],
        "outcome_1":    rec["outcome_1"],
        "volume":       rec["volume"],
        "team0_won":    team0_won,
        "underdog_won": underdog_won,
        "min_price":    round(min_price, 4),
        "max_price":    round(max_price, 4),
        "n_history_pts": len(history),
        "has_vsignal":  len(signals) > 0,
        "n_signals":    len(signals),
        "signals":      signals,
    }
    return base


def main():
    print("=== Step 3: V型信号检测 ===")
    print(f"参数: drop≥{DROP_THRESHOLD*100:.0f}%, rebound≥{REBOUND_THRESHOLD*100:.0f}%, 持续≥{MIN_REBOUND_MINS}min")

    files = list(HISTORY_DIR.glob("*.json"))
    print(f"共 {len(files)} 个比赛文件\n")

    all_results = []
    signal_results = []
    errors = 0

    for i, fpath in enumerate(files, 1):
        try:
            result = analyze_file(fpath)
            if result is None:
                continue
            all_results.append(result)
            if result["has_vsignal"]:
                signal_results.append(result)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ✗ {fpath.name}: {e}")

        if i % 200 == 0:
            print(f"  处理进度: {i}/{len(files)} | 信号={len(signal_results)}")

    # 保存结果
    with open(ALL_GAMES_FILE, "w") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(SIGNALS_FILE, "w") as f:
        for r in signal_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── 统计报告 ─────────────────────────────────────────────
    total = len(all_results)
    with_signals = len(signal_results)

    # 基础逆转率（所有场次中弱势方获胜比例）
    underdog_wins_all = [r for r in all_results if r["underdog_won"] is True]
    base_reversal_rate = len(underdog_wins_all) / total if total else 0

    # 信号命中率（有V型信号的场次中弱势方获胜比例）
    signal_wins = [r for r in signal_results if r["underdog_won"] is True]
    signal_win_rate = len(signal_wins) / with_signals if with_signals else 0

    # 信号在所有比赛中的覆盖率
    signal_coverage = with_signals / total if total else 0

    print(f"\n{'='*50}")
    print(f"  总比赛场次:           {total:,}")
    print(f"  弱势方基础胜率:       {base_reversal_rate:.2%}  ({len(underdog_wins_all)}/{total})")
    print(f"  ─────────────────────────────────")
    print(f"  V型信号场次:          {with_signals:,} ({signal_coverage:.1%} 覆盖率)")
    print(f"  信号场次弱势方胜率:   {signal_win_rate:.2%}  ({len(signal_wins)}/{with_signals})")
    print(f"  信号提升倍数:         {signal_win_rate/base_reversal_rate:.1f}x" if base_reversal_rate else "")
    print(f"  错误:                 {errors}")
    print(f"{'='*50}")
    print(f"\n✓ 结果已保存:")
    print(f"  {ALL_GAMES_FILE}")
    print(f"  {SIGNALS_FILE}")


if __name__ == "__main__":
    main()
