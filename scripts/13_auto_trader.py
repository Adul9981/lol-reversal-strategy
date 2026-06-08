"""
Script 13: LoL 反转策略自动交易机器人

功能：
  每 30 秒轮询一次，全自动完成以下流程：
  1. 检测 LCK/LEC 当前正在直播的比赛
  2. 从 LoL Livestats 获取实时战局（游戏时间 / 金币差 / 龙数）
  3. 从 Polymarket CLOB 获取当前赔率
  4. 按规则检测信号（17-30分 + 赔率<30% + 金差>-3000 + 对方龙≤3）
  5. 触发时自动下单
  6. 持仓管理：赔率涨到 3x 卖出一半，剩余持有到结算
  7. 记录所有信号和交易（含「本该买但没买」的复盘记录）

环境变量（在服务器上 export，或放在同目录 .env 文件中）：
  PRIVATE_KEY              MetaMask 私钥，格式 0x...
  POLYMARKET_API_KEY       Polymarket CLOB API Key
  POLYMARKET_API_SECRET    Polymarket CLOB API Secret
  POLYMARKET_API_PASS      Polymarket CLOB API Passphrase
  BANKROLL                 总资金 USDC（默认 500）
  DRY_RUN                  true=只打印不下单（默认 true，改为 false 才真实交易）
  MAX_DAILY_LOSS           每日最大亏损保护 USDC（默认 50）

安装依赖：
  pip install py-clob-client python-dotenv requests
"""

import os, json, time, logging
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import requests
import urllib3
urllib3.disable_warnings()

# 尝试加载 .env 文件（VPS 上直接 export 环境变量即可）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# 配置（全部从环境变量读取，不要在代码里写明文）
# ─────────────────────────────────────────────────────────────────────────────
PRIVATE_KEY       = os.getenv("PRIVATE_KEY", "")
PM_API_KEY        = os.getenv("POLYMARKET_API_KEY", "")
PM_API_SECRET     = os.getenv("POLYMARKET_API_SECRET", "")
PM_API_PASS       = os.getenv("POLYMARKET_API_PASS", "")
BANKROLL          = float(os.getenv("BANKROLL", "500"))
DRY_RUN           = os.getenv("DRY_RUN", "true").lower() != "false"
MAX_DAILY_LOSS    = float(os.getenv("MAX_DAILY_LOSS", "50"))

LOL_API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
POLL_INTERVAL = 30          # 轮询间隔（秒）
TARGET_LEAGUES = {"LCK", "LEC"}   # 监控的联赛

# ─────────────────────────────────────────────────────────────────────────────
# 路径
# ─────────────────────────────────────────────────────────────────────────────
BASE         = Path(__file__).parent.parent
RULES_FILE   = BASE / "data/rules/trading_rules.json"
MARKETS_FILE = BASE / "data/game_winner_markets/game_winner_markets.json"
STATE_FILE   = BASE / "data/bot_state.json"   # 持久化持仓状态
SIGNAL_LOG   = BASE / "data/bot_signals.jsonl" # 所有触发的信号
TRADE_LOG    = BASE / "data/bot_trades.jsonl"  # 所有实际交易

# ─────────────────────────────────────────────────────────────────────────────
# 日志
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE / "data/bot.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("lol-bot")

# ─────────────────────────────────────────────────────────────────────────────
# HTTP Session
# ─────────────────────────────────────────────────────────────────────────────
lol_s = requests.Session()
lol_s.verify = False
lol_s.headers["x-api-key"] = LOL_API_KEY

pm_s = requests.Session()
pm_s.verify = False


# ═════════════════════════════════════════════════════════════════════════════
# 规则引擎
# ═════════════════════════════════════════════════════════════════════════════

def load_rules() -> dict:
    with open(RULES_FILE, encoding="utf-8") as f:
        return json.load(f)

def check_signal(rules: dict, game_min: float, price: float,
                 gold_diff: float, opp_dragons: int) -> tuple[bool, str]:
    """
    检查是否满足买入条件。
    返回 (should_buy, reason_string)

    核心条件（AND 关系）：
      ① 游戏时间 17–30 分钟
      ② 弱势方赔率 < 30%
      ③ 金币差 > -3000（弱势方没被拉开）
      ④ 对方龙数 ≤ 3

    可选加分（不影响入场，影响仓位倍数）：
      + 金差 > -2000    → 仓位 1.5x
      + 对方龙数 ≤ 2   → 仓位 1.2x
    """
    reasons = []
    multiplier = 1.0

    # ① 时间窗口
    if not (17 <= game_min <= 30):
        return False, f"时间窗口不符 ({game_min:.1f}分，需17-30分)"

    # ② 赔率阈值
    if price >= 0.30:
        return False, f"赔率不够低 ({price:.0%}，需<30%)"

    # ③ 金币差
    if gold_diff < -3000:
        return False, f"金币差过大 ({gold_diff:+,.0f}，需>-3000)"

    # ④ 对方龙数
    if opp_dragons > 3:
        return False, f"对方龙数过多 ({opp_dragons}条，需≤3)"

    # 加分条件
    reasons.append(f"时间{game_min:.1f}分")
    reasons.append(f"赔率{price:.0%}")
    reasons.append(f"金差{gold_diff:+,.0f}")
    reasons.append(f"对方龙{opp_dragons}条")

    if gold_diff > -2000:
        multiplier *= 1.5
        reasons.append("金差<2000加仓↑")
    if opp_dragons <= 2:
        multiplier *= 1.2
        reasons.append("龙≤2加仓↑")

    return True, " | ".join(reasons) + f" | 仓位倍数×{multiplier:.1f}"


def calc_position_size(rules: dict, price: float, multiplier: float = 1.0) -> float:
    """计算下注金额（凯利公式 × 总资金 × 倍数）"""
    if price < 0.10:
        base_pct = 0.0075   # 彩票型：0.75%
    elif price < 0.20:
        base_pct = 0.0125   # 深度型：1.25%
    else:
        base_pct = 0.015    # 普通型：1.5%

    size = BANKROLL * base_pct * multiplier
    size = min(size, BANKROLL * 0.05)  # 单笔不超过总资金 5%
    return round(size, 2)


# ═════════════════════════════════════════════════════════════════════════════
# LoL Esports API
# ═════════════════════════════════════════════════════════════════════════════

LEAGUE_IDS = {
    "LCK": "98767991310872058",
    "LEC": "98767991302996019",
}

def fetch_live_matches() -> list[dict]:
    """
    返回当前正在直播的 LCK/LEC 比赛列表。
    每项格式：{
        match_id, league, team_a, team_b,
        game_id, game_number, lol_game_id
    }
    """
    try:
        r = lol_s.get(
            "https://esports-api.lolesports.com/persisted/gw/getLiveMatches",
            params={"hl": "en-US"}, timeout=10
        )
        if r.status_code != 200:
            return []
        data = r.json().get("data", {}).get("schedule", {}).get("events", [])
    except Exception as e:
        log.warning(f"getLiveMatches 失败: {e}")
        return []

    live = []
    for event in data:
        league_slug = event.get("league", {}).get("slug", "").upper()
        # 匹配 LCK / LEC
        if not any(t in league_slug for t in ["LCK", "LEC"]):
            continue
        league = "LCK" if "LCK" in league_slug else "LEC"

        match = event.get("match", {})
        teams = match.get("teams", [])
        if len(teams) < 2:
            continue
        team_a = teams[0].get("name", "")
        team_b = teams[1].get("name", "")

        # 找当前正在进行的 game
        for game in match.get("games", []):
            if game.get("state") == "inProgress":
                live.append({
                    "match_id":    match.get("id", ""),
                    "league":      league,
                    "team_a":      team_a,
                    "team_b":      team_b,
                    "game_number": game.get("number", 1),
                    "lol_game_id": game.get("id", ""),
                })
    return live


def fetch_game_state(lol_game_id: str, game_start_ts: Optional[float]) -> Optional[dict]:
    """
    从 Livestats 获取当前战局快照。
    返回 {game_min, gold_diff, our_side_gold, opp_side_gold,
           our_dragons, opp_dragons, kills_us, kills_opp}
    或 None（如果无法获取）
    """
    if not lol_game_id:
        return None

    # 当前时间戳，向前 2 分钟取最近帧
    now_ts = datetime.now(timezone.utc)
    window_ts = (now_ts - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        url = f"https://feed.lolesports.com/livestats/v1/window/{lol_game_id}"
        r = lol_s.get(url, params={"startingTime": window_ts}, timeout=10)
        if r.status_code != 200:
            return None
        frames = r.json().get("frames", [])
        if not frames:
            return None
    except Exception as e:
        log.debug(f"Livestats 请求失败 {lol_game_id}: {e}")
        return None

    # 取最新帧
    frame = frames[-1]
    game_time_s = frame.get("rfc460Timestamp", "")

    # 如果知道游戏开始时间，计算精确游戏分钟数
    if game_start_ts:
        try:
            frame_ts = datetime.fromisoformat(game_time_s.replace("Z", "+00:00")).timestamp()
            game_min = (frame_ts - game_start_ts) / 60
        except Exception:
            game_min = frame.get("gameState", {}).get("gameTime", 0) / 60
    else:
        game_min = frame.get("gameState", {}).get("gameTime", 0) / 60

    teams_data = frame.get("blueTeam", {}), frame.get("redTeam", {})

    # 统计两队数据
    results = []
    for team in teams_data:
        total_gold = sum(p.get("totalGold", 0) for p in team.get("participants", []))
        dragons    = len(team.get("dragons", []))
        kills      = sum(p.get("kills", 0) for p in team.get("participants", []))
        results.append({"gold": total_gold, "dragons": dragons, "kills": kills})

    if len(results) < 2:
        return None

    blue, red = results[0], results[1]
    # gold_diff 从蓝队视角（正值 = 蓝队领先）
    gold_diff_blue = blue["gold"] - red["gold"]

    return {
        "game_min":   round(game_min, 1),
        "blue_gold":  blue["gold"],
        "red_gold":   red["gold"],
        "gold_diff_blue": gold_diff_blue,  # 蓝队 - 红队
        "blue_dragons":  blue["dragons"],
        "red_dragons":   red["dragons"],
        "blue_kills":    blue["kills"],
        "red_kills":     red["kills"],
        "frame_ts":      game_time_s,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Polymarket 市场匹配 & 价格
# ═════════════════════════════════════════════════════════════════════════════

def load_active_markets() -> list[dict]:
    """加载 game_winner_markets.json，过滤出活跃的 LCK/LEC 市场"""
    with open(MARKETS_FILE, encoding="utf-8") as f:
        all_markets = json.load(f)
    return [m for m in all_markets if m.get("league") in TARGET_LEAGUES]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_market(markets: list[dict], team_a: str, team_b: str,
                 game_number: int) -> Optional[dict]:
    """
    在 Polymarket 市场列表中找到对应的 Game N Winner 市场。
    匹配逻辑：
      1. 两支队名都能在 outcome_0 / outcome_1 中找到（相似度 > 0.6）
      2. game_question 中包含 "Game N"
    """
    target_game = f"Game {game_number}"
    best, best_score = None, 0.0

    for m in markets:
        q = m.get("game_question", "")
        if target_game not in q:
            continue
        o0 = m.get("outcome_0", "")
        o1 = m.get("outcome_1", "")

        # 两队都要能匹配上
        score_aa = max(_similarity(team_a, o0), _similarity(team_a, o1))
        score_bb = max(_similarity(team_b, o0), _similarity(team_b, o1))

        if score_aa > 0.55 and score_bb > 0.55:
            score = (score_aa + score_bb) / 2
            if score > best_score:
                best_score = score
                best = m

    return best


def get_current_price(token_id: str) -> Optional[float]:
    """
    从 Polymarket CLOB 获取指定 token 的当前中间价（0-1）。
    """
    try:
        r = pm_s.get(
            f"https://clob.polymarket.com/midpoint",
            params={"token_id": token_id}, timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            return float(data.get("mid", 0))
    except Exception as e:
        log.debug(f"获取价格失败 {token_id[:16]}...: {e}")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# 下单执行
# ═════════════════════════════════════════════════════════════════════════════

def execute_buy(token_id: str, price: float, size_usdc: float,
                reason: str, market: dict) -> Optional[dict]:
    """
    在 Polymarket CLOB 执行买单。
    DRY_RUN=true 时只打印，不实际下单。
    """
    trade_record = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "action":      "BUY",
        "token_id":    token_id,
        "price":       price,
        "size_usdc":   size_usdc,
        "reason":      reason,
        "market":      market.get("game_question", ""),
        "dry_run":     DRY_RUN,
        "order_id":    None,
    }

    if DRY_RUN:
        log.info(f"  [DRY RUN] 模拟买入 {size_usdc:.2f} USDC @ {price:.0%} | {reason}")
        _write_log(TRADE_LOG, trade_record)
        return trade_record

    # ── 真实下单（需要 py-clob-client）─────────────────────────────────────
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds, OrderArgs

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=PRIVATE_KEY,
            creds=ApiCreds(
                api_key=PM_API_KEY,
                api_secret=PM_API_SECRET,
                api_passphrase=PM_API_PASS,
            ),
        )

        resp = client.create_and_post_order(OrderArgs(
            token_id=token_id,
            price=round(price, 2),
            size=round(size_usdc, 2),
            side="BUY",
            fee_rate_bps=0,
        ))
        trade_record["order_id"] = resp.get("orderID", "")
        log.info(f"  ✅ 买入成功 order={trade_record['order_id']}")

    except ImportError:
        log.error("py-clob-client 未安装，请运行: pip install py-clob-client")
        trade_record["order_id"] = "ERROR_NO_CLIENT"
    except Exception as e:
        log.error(f"  ❌ 下单失败: {e}")
        trade_record["order_id"] = f"ERROR: {e}"

    _write_log(TRADE_LOG, trade_record)
    return trade_record


def execute_sell(token_id: str, size_usdc: float, reason: str) -> Optional[dict]:
    """卖出指定数量的 token（止盈或平仓）"""
    trade_record = {
        "ts":       datetime.now(timezone.utc).isoformat(),
        "action":   "SELL",
        "token_id": token_id,
        "size_usdc": size_usdc,
        "reason":   reason,
        "dry_run":  DRY_RUN,
    }

    if DRY_RUN:
        log.info(f"  [DRY RUN] 模拟卖出 {size_usdc:.2f} tokens | {reason}")
        _write_log(TRADE_LOG, trade_record)
        return trade_record

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds, OrderArgs

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=PRIVATE_KEY,
            creds=ApiCreds(
                api_key=PM_API_KEY,
                api_secret=PM_API_SECRET,
                api_passphrase=PM_API_PASS,
            ),
        )

        # 获取当前卖价
        price_now = get_current_price(token_id)
        if price_now is None:
            price_now = 0.5  # fallback

        resp = client.create_and_post_order(OrderArgs(
            token_id=token_id,
            price=round(price_now - 0.01, 2),  # 略低于市价，确保成交
            size=round(size_usdc, 2),
            side="SELL",
            fee_rate_bps=0,
        ))
        trade_record["order_id"] = resp.get("orderID", "")
        log.info(f"  ✅ 卖出成功 order={trade_record['order_id']}")

    except Exception as e:
        log.error(f"  ❌ 卖出失败: {e}")
        trade_record["order_id"] = f"ERROR: {e}"

    _write_log(TRADE_LOG, trade_record)
    return trade_record


# ═════════════════════════════════════════════════════════════════════════════
# 持仓状态管理
# ═════════════════════════════════════════════════════════════════════════════

def load_state() -> dict:
    """加载持久化状态（程序重启后不丢失持仓）"""
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "positions": {},      # token_id -> position_info
        "daily_loss": 0.0,
        "daily_date": "",
        "triggered_today": [], # 今天已触发信号的 token_id，避免重复买
    }


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_daily_reset(state: dict):
    """每天 UTC 0 点重置每日统计"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state["daily_date"] != today:
        state["daily_date"] = today
        state["daily_loss"] = 0.0
        state["triggered_today"] = []
        log.info(f"📅 新的一天 {today}，重置每日统计")


def manage_positions(state: dict):
    """检查所有持仓，执行止盈或平仓"""
    positions = state.get("positions", {})
    to_remove = []

    for token_id, pos in positions.items():
        current_price = get_current_price(token_id)
        if current_price is None:
            continue

        entry_price = pos["entry_price"]
        size_held   = pos["size_held"]   # 当前持有数量（token 数）
        half_exited = pos.get("half_exited", False)
        game_min_entry = pos.get("game_min_entry", 0)

        # 检查是否已结算（价格接近 0 或 1）
        if current_price >= 0.95:
            log.info(f"  🏆 持仓结算（赢）token={token_id[:12]}...")
            pnl = size_held * (current_price - entry_price)
            log.info(f"  盈亏: +{pnl:.2f} USDC")
            _update_pnl(state, pnl)
            to_remove.append(token_id)
            continue

        if current_price <= 0.03:
            log.info(f"  💸 持仓结算（输）token={token_id[:12]}...")
            pnl = -size_held * entry_price
            _update_pnl(state, pnl)
            to_remove.append(token_id)
            continue

        # 止盈：赔率涨到买入价 3x → 卖出一半
        if not half_exited and current_price >= entry_price * 3:
            sell_size = size_held / 2
            log.info(f"  📈 3x 止盈！卖出一半 {sell_size:.2f} tokens @ {current_price:.0%}")
            execute_sell(token_id, sell_size, f"3x止盈: {entry_price:.0%}→{current_price:.0%}")
            pos["size_held"]   -= sell_size
            pos["half_exited"]  = True
            log.info(f"  剩余持仓 {pos['size_held']:.2f} tokens，继续持有到结算")

        # 超时保护：超过 35 分钟还没结算，且没有盈利，考虑卖出
        # （暂时只打 warning，不强制卖出——保持手动决策权）
        if game_min_entry and (datetime.now(timezone.utc).timestamp() -
                                pos.get("entry_ts", 0)) > 35 * 60:
            if current_price < entry_price * 1.5:
                log.warning(f"  ⏰ 持仓超过35分钟，赔率未涨，请注意: {token_id[:12]}...")

    for t in to_remove:
        del state["positions"][t]


def _update_pnl(state: dict, pnl: float):
    if pnl < 0:
        state["daily_loss"] = state.get("daily_loss", 0) + abs(pnl)


# ═════════════════════════════════════════════════════════════════════════════
# 日志辅助
# ═════════════════════════════════════════════════════════════════════════════

def _write_log(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_signal(token_id: str, triggered: bool, reason: str,
               game_info: dict, price: float, size: float):
    record = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "triggered": triggered,
        "reason":    reason,
        "price":     price,
        "size":      size,
        "game":      game_info,
        "token_id":  token_id,
    }
    _write_log(SIGNAL_LOG, record)


# ═════════════════════════════════════════════════════════════════════════════
# 主循环
# ═════════════════════════════════════════════════════════════════════════════

def run():
    mode = "🟡 DRY RUN（只记录，不下单）" if DRY_RUN else "🔴 LIVE（真实交易！）"
    log.info(f"{'='*60}")
    log.info(f"  LoL 反转策略机器人启动")
    log.info(f"  模式: {mode}")
    log.info(f"  总资金: ${BANKROLL}  每日止损: ${MAX_DAILY_LOSS}")
    log.info(f"  监控联赛: {TARGET_LEAGUES}")
    log.info(f"{'='*60}")

    rules   = load_rules()
    markets = load_active_markets()
    state   = load_state()
    log.info(f"  加载 {len(markets)} 个活跃市场")

    while True:
        try:
            _main_tick(rules, markets, state)
            save_state(state)
        except KeyboardInterrupt:
            log.info("用户中断，机器人停止")
            save_state(state)
            break
        except Exception as e:
            log.error(f"主循环异常（将在 {POLL_INTERVAL}s 后重试）: {e}")

        time.sleep(POLL_INTERVAL)


def _main_tick(rules: dict, markets: list[dict], state: dict):
    check_daily_reset(state)

    # 每日亏损保护
    if state["daily_loss"] >= MAX_DAILY_LOSS:
        log.warning(f"⛔ 每日亏损 ${state['daily_loss']:.2f} 已达上限，今日暂停交易")
        _check_existing_positions(state)
        return

    # ── 1. 检测直播比赛 ───────────────────────────────────────────────────
    live_matches = fetch_live_matches()
    if not live_matches:
        log.debug("无直播比赛")
        _check_existing_positions(state)
        return

    log.info(f"  📡 {len(live_matches)} 场直播: " +
             ", ".join(f"{m['team_a']} vs {m['team_b']} G{m['game_number']}"
                       for m in live_matches))

    # ── 2. 逐场处理 ──────────────────────────────────────────────────────
    for match in live_matches:
        team_a = match["team_a"]
        team_b = match["team_b"]
        game_n = match["game_number"]
        lol_id = match["lol_game_id"]

        # 匹配 Polymarket 市场
        pm_market = match_market(markets, team_a, team_b, game_n)
        if not pm_market:
            log.debug(f"  未找到 Polymarket 市场: {team_a} vs {team_b} G{game_n}")
            continue

        # 获取战局快照
        game_state = fetch_game_state(lol_id, None)
        if not game_state:
            log.debug(f"  Livestats 无数据: {lol_id}")
            continue

        game_min = game_state["game_min"]

        # ── 3. 分别检查两队的赔率 & 信号 ──────────────────────────────────
        for side in ("0", "1"):
            token_id  = pm_market[f"token_{side}"]
            team_name = pm_market[f"outcome_{side}"]

            # 跳过已有持仓 / 今日已触发
            if token_id in state["positions"]:
                continue
            if token_id in state.get("triggered_today", []):
                continue

            # 获取当前赔率
            price = get_current_price(token_id)
            if price is None:
                continue

            # 判断该队是否是"弱势方"（gold_diff 视角）
            # token_0 对应 outcome_0，但 blue/red 映射需要运行时确认
            # 简化处理：只要赔率 < 0.30 就作为弱势方处理
            if price >= 0.30:
                continue  # 不是低赔率，跳过

            # 从 Livestats 视角判断金币差和龙数
            # 这里用蓝队视角：如果 token 对应蓝队，gold_diff = blue - red
            # 如果对应红队，gold_diff = red - blue = -blue_gold_diff
            # 简化：取绝对值，如果任一队经济差 < 3000 就允许
            abs_gold_diff = abs(game_state["gold_diff_blue"])
            # 弱势方金差 = 负数（他们少），所以用 -abs
            gold_diff_weak = -abs_gold_diff

            # 对方龙数 = 另一队的龙数（谁赔率低，对方就是领先队）
            # 领先队一般龙多，这里取两队龙数的较大值作为"对方龙数"
            opp_dragons = max(game_state["blue_dragons"], game_state["red_dragons"])

            # 信号检测
            triggered, reason = check_signal(
                rules, game_min, price, gold_diff_weak, opp_dragons
            )

            game_info = {
                "team": team_name, "vs": team_b if side == "0" else team_a,
                "game_n": game_n, "league": match["league"],
                "game_min": game_min, "gold_diff": gold_diff_weak,
                "opp_dragons": opp_dragons,
            }

            # 记录信号（不管有没有触发）
            size = calc_position_size(rules, price) if triggered else 0
            log_signal(token_id, triggered, reason, game_info, price, size)

            if not triggered:
                log.debug(f"  ⚪ 未触发 [{team_name}]: {reason}")
                continue

            # ── 4. 触发！执行买入 ─────────────────────────────────────────
            log.info(f"  🚨 信号触发！{match['league']} {team_name} @ {price:.0%}")
            log.info(f"     {reason}")
            log.info(f"     建议仓位: ${size:.2f}")

            trade = execute_buy(token_id, price, size, reason, pm_market)

            # 记录持仓
            if trade:
                state["positions"][token_id] = {
                    "team":         team_name,
                    "market":       pm_market.get("game_question", ""),
                    "entry_price":  price,
                    "entry_ts":     datetime.now(timezone.utc).timestamp(),
                    "size_held":    size / price,  # token 数量 = USDC / 价格
                    "size_usdc":    size,
                    "game_min_entry": game_min,
                    "half_exited":  False,
                    "lol_game_id":  lol_id,
                }
                state["triggered_today"].append(token_id)

    # ── 5. 管理已有持仓 ──────────────────────────────────────────────────
    _check_existing_positions(state)


def _check_existing_positions(state: dict):
    if state["positions"]:
        log.info(f"  📊 当前持仓 {len(state['positions'])} 个，检查止盈条件...")
        manage_positions(state)


# ═════════════════════════════════════════════════════════════════════════════
# 入口
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LoL 反转策略自动交易机器人")
    parser.add_argument("--live", action="store_true",
                        help="开启真实交易（默认 DRY RUN）")
    parser.add_argument("--bankroll", type=float,
                        help="覆盖总资金设置（USDC）")
    args = parser.parse_args()

    if args.live:
        DRY_RUN = False
        if not PRIVATE_KEY:
            print("❌ 错误：开启真实交易需要设置 PRIVATE_KEY 环境变量")
            exit(1)
        print("⚠️  警告：即将使用真实资金交易！按 Ctrl+C 中止，5 秒后开始...")
        time.sleep(5)

    if args.bankroll:
        BANKROLL = args.bankroll

    run()
