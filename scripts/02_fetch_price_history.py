"""
Step 2: 为每场已结束的比赛拉取赔率历史
只处理: ended=True 且 volume>100 且 token_0 非空

输出: data/price_history/{event_id}.json
每个文件包含: event元数据 + token_0 的价格时序

说明:
- token_0 对应 outcome_0 (团队A)
- 价格=1 表示团队A获胜，价格=0 表示失败
- 我们只需要其中一个token的历史（另一个价格=1-p）
"""
import json
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR   = Path(__file__).parent.parent / "data"
EVENTS_FILE = DATA_DIR / "events.jsonl"
OUT_DIR    = DATA_DIR / "price_history"
CLOB_BASE  = "https://clob.polymarket.com"

MIN_VOLUME = 100   # 忽略小市场
MAX_WORKERS = 8    # 并发请求数


def load_events():
    events = []
    with open(EVENTS_FILE) as f:
        for line in f:
            e = json.loads(line)
            if e["ended"] and e["volume"] >= MIN_VOLUME and e["token_0"]:
                events.append(e)
    return events


def fetch_history(token_id, retries=4):
    """拉取单个token的价格历史"""
    url = f"{CLOB_BASE}/prices-history"
    params = {"market": token_id, "interval": "max", "fidelity": "1"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json().get("history", [])
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                return None  # 失败，返回None
    return None


def process_event(event):
    out_file = OUT_DIR / f"{event['event_id']}.json"
    if out_file.exists():
        return "skip"

    history = fetch_history(event["token_0"])
    if history is None:
        return "error"

    record = {
        "event_id":        event["event_id"],
        "title":           event["title"],
        "outcome_0":       event["outcome_0"],
        "outcome_1":       event["outcome_1"],
        "last_price_0":    event["last_price_0"],  # 1.0 = outcome_0 won
        "game_start_time": event["game_start_time"],
        "end_date":        event["end_date"],
        "volume":          event["volume"],
        "token_0":         event["token_0"],
        "history":         history,
    }
    out_file.write_text(json.dumps(record, ensure_ascii=False))
    return "ok" if history else "empty"


def main():
    OUT_DIR.mkdir(exist_ok=True)

    print("=== Step 2: 拉取赔率历史 ===")
    events = load_events()
    print(f"需要处理: {len(events)} 场 (ended + volume≥{MIN_VOLUME})")

    # 检查已完成的
    already_done = sum(1 for e in events if (OUT_DIR / f"{e['event_id']}.json").exists())
    print(f"已完成: {already_done}, 待处理: {len(events) - already_done}")

    stats = {"ok": 0, "empty": 0, "error": 0, "skip": 0}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_event, e): e for e in events}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            stats[result] = stats.get(result, 0) + 1

            if i % 100 == 0 or i == len(events):
                pct = i / len(events) * 100
                print(f"[{i:5d}/{len(events)}] {pct:.1f}% | ok={stats['ok']} empty={stats['empty']} err={stats['error']} skip={stats['skip']}")

    print(f"\n✓ 完成: {stats}")


if __name__ == "__main__":
    main()
