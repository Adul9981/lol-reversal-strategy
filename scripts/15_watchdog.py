#!/usr/bin/env python3
"""
Script 15 · 自管理看守 (Watchdog)

职责：
  1. 每隔 15 分钟被 launchd 唤醒
  2. 检查 Polymarket 上是否有活跃的 LoL 对阵市场
  3. 有市场 → 确保 14_signal_monitor.py 在运行（崩溃了就重启）
  4. 连续 30 分钟没有市场 → 停止 monitor，等下次唤醒再检查
  5. 所有行为写入 watchdog.log

由 launchd plist 负责调度，用户无需手动操作。
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings()

# ══════════════════════════════════════════════════════════════════
# 路径配置
# ══════════════════════════════════════════════════════════════════

BASE       = Path(__file__).parent.parent
MONITOR_PY = BASE / "scripts" / "14_signal_monitor.py"
PID_FILE   = BASE / "data" / "monitor.pid"
LOG_FILE   = BASE / "data" / "monitor.log"
WD_LOG     = BASE / "data" / "watchdog.log"
NO_MKT_FILE = BASE / "data" / "no_market_since.txt"  # 记录「无市场」起始时间

PYTHON     = sys.executable   # 用当前 Python 解释器
NO_MKT_TIMEOUT = 30 * 60     # 连续 30 分钟无市场才停止 monitor

# ══════════════════════════════════════════════════════════════════
# 日志
# ══════════════════════════════════════════════════════════════════

def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(WD_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ══════════════════════════════════════════════════════════════════
# macOS 通知（仅用于重要事件）
# ══════════════════════════════════════════════════════════════════

def notify(title: str, body: str) -> None:
    title = title.replace('"', "'")
    body  = body.replace('"', "'")
    subprocess.run(
        ["osascript", "-e", f'display notification "{body}" with title "{title}"'],
        capture_output=True,
    )

# ══════════════════════════════════════════════════════════════════
# 市场检测：Polymarket 上是否有活跃对阵局？
# ══════════════════════════════════════════════════════════════════

EXCLUDE_KEYWORDS = ["season", "winner", "champion", "challenger", "spring",
                    "summer", "split", "playoff", "worlds", "msi", "region"]

def has_active_game_markets() -> bool:
    """
    返回 True 表示当前 Polymarket 上有 LoL 队伍对阵市场（非赛季级）。
    """
    TAG_SLUGS = ["league-of-legends", "esports"]
    seen_ids: set = set()
    events: list = []
    for tag in TAG_SLUGS:
        try:
            r = requests.get(
                "https://gamma-api.polymarket.com/events",
                params={
                    "active":   "true",
                    "closed":   "false",
                    "archived": "false",
                    "tag_slug": tag,
                    "limit":    100,
                },
                timeout=12,
            )
            r.raise_for_status()
            for ev in r.json():
                if ev.get("id") not in seen_ids:
                    seen_ids.add(ev.get("id"))
                    events.append(ev)
        except Exception as e:
            log(f"⚠️  Gamma API ({tag}) 错误: {e}")

    if not events:
        return False

    for ev in events:
        title_lower = ev.get("title", "").lower()
        # 只对非对战事件（不含 " vs "）才做关键词过滤
        if " vs " not in title_lower:
            if any(kw in title_lower for kw in EXCLUDE_KEYWORDS):
                continue
        for m in ev.get("markets", []):
            if not m.get("active") or m.get("closed"):
                continue
            try:
                outcomes = json.loads(m.get("outcomes", "[]"))
                outcome_set = set(o.lower() for o in outcomes)
                if len(outcomes) == 2 and outcome_set not in [{"yes", "no"}, {"over", "under"}, {"odd", "even"}]:
                    return True  # 找到一个有效对阵市场即返回
            except Exception:
                continue

    return False

# ══════════════════════════════════════════════════════════════════
# 进程管理
# ══════════════════════════════════════════════════════════════════

def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None

def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

def start_monitor() -> int:
    """启动 monitor，返回新 PID"""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [PYTHON, "-u", str(MONITOR_PY)],
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,   # 脱离当前会话，不受终端关闭影响
    )
    PID_FILE.write_text(str(proc.pid))
    return proc.pid

def stop_monitor() -> None:
    pid = read_pid()
    if pid and is_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            log(f"🛑 Monitor 已停止 (PID {pid})")
        except Exception as e:
            log(f"⚠️  停止 Monitor 失败: {e}")
    PID_FILE.unlink(missing_ok=True)

# ══════════════════════════════════════════════════════════════════
# 主逻辑
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    log("── Watchdog 唤醒 ──")

    market_active = has_active_game_markets()
    pid           = read_pid()
    monitor_alive = pid is not None and is_running(pid)

    if market_active:
        # 有市场 → 清除「无市场计时器」
        NO_MKT_FILE.unlink(missing_ok=True)

        if monitor_alive:
            log(f"✅ Monitor 运行中 (PID {pid})，市场活跃，无需操作")
        else:
            # Monitor 没在跑（首次启动 or 崩溃）→ 重启
            reason = "首次启动" if pid is None else f"PID {pid} 已崩溃，重启"
            new_pid = start_monitor()
            log(f"🚀 Monitor 已启动 ({reason})，新 PID: {new_pid}")
            notify("LoL 监控 已启动", f"检测到活跃市场，Monitor 启动 (PID {new_pid})")

    else:
        # 无活跃市场
        if not NO_MKT_FILE.exists():
            NO_MKT_FILE.write_text(str(time.time()))
            log("📭 无活跃市场，开始计时（30分钟后停止 Monitor）")
        else:
            no_mkt_since = float(NO_MKT_FILE.read_text().strip())
            elapsed      = time.time() - no_mkt_since
            log(f"📭 无活跃市场已持续 {elapsed/60:.1f} 分钟")

            if elapsed >= NO_MKT_TIMEOUT and monitor_alive:
                stop_monitor()
                NO_MKT_FILE.unlink(missing_ok=True)
                notify("LoL 监控 已暂停", "30分钟无市场，Monitor 已停止，有比赛时自动重启")

    log("── Watchdog 完成 ──\n")


if __name__ == "__main__":
    main()
