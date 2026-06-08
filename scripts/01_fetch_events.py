"""
Step 1: 拉取所有 Polymarket LoL 比赛事件
series_id=10311 = League of Legends
使用 offset 分页（keyset cursor 有 bug，不可用）
总量约 2000-2100 条
输出: data/events.jsonl
"""
import json
import time
import requests
from pathlib import Path

BASE      = "https://gamma-api.polymarket.com"
SERIES_ID = 10311
DATA_DIR  = Path(__file__).parent.parent / "data"
OUT_FILE  = DATA_DIR / "events.jsonl"
PAGE_SIZE = 100


def fetch_page(offset, retries=5):
    params = {
        "series_id": SERIES_ID,
        "limit":     PAGE_SIZE,
        "offset":    offset,
        "order":     "startDate",
        "ascending": "true",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(f"{BASE}/events", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            wait = 2 ** attempt
            print(f"  ⚠ offset={offset} 重试{attempt+1}: {e.__class__.__name__} | 等待{wait}s")
            time.sleep(wait)
    return []


def parse_event(e):
    market = e["markets"][0] if e.get("markets") else {}

    def safe_json(v):
        if isinstance(v, str):
            try: return json.loads(v)
            except: return []
        return v or []

    tokens   = safe_json(market.get("clobTokenIds", "[]"))
    outcomes = safe_json(market.get("outcomes", "[]"))
    prices   = safe_json(market.get("outcomePrices", "[]"))

    return {
        "event_id":        e["id"],
        "title":           e.get("title", ""),
        "start_date":      e.get("startDate", ""),
        "end_date":        e.get("endDate", ""),
        "game_start_time": market.get("gameStartTime", ""),
        "active":          bool(e.get("active")),
        "ended":           bool(e.get("ended")),
        "volume":          float(market.get("volumeNum") or 0),
        "outcome_0":       outcomes[0] if len(outcomes) > 0 else "",
        "outcome_1":       outcomes[1] if len(outcomes) > 1 else "",
        "last_price_0":    float(prices[0]) if len(prices) > 0 else None,
        "last_price_1":    float(prices[1]) if len(prices) > 1 else None,
        "token_0":         tokens[0] if len(tokens) > 0 else "",
        "token_1":         tokens[1] if len(tokens) > 1 else "",
    }


def main():
    DATA_DIR.mkdir(exist_ok=True)
    print("=== Step 1: 拉取 Polymarket LoL 事件（offset 分页）===")

    all_events = []
    offset = 0

    while True:
        batch = fetch_page(offset)
        if not batch:
            print(f"  offset={offset}: 无数据，拉取完毕")
            break

        parsed = [parse_event(e) for e in batch]
        all_events.extend(parsed)

        ended  = sum(1 for e in parsed if e["ended"])
        active = sum(1 for e in parsed if e["active"] and not e["ended"])
        print(f"offset={offset:5d} | +{len(batch):3d} (ended={ended}, active={active}) | total={len(all_events)}")

        offset += PAGE_SIZE
        time.sleep(0.3)

    # 去重（以 event_id 为 key）
    seen = set()
    deduped = []
    for e in all_events:
        if e["event_id"] not in seen:
            seen.add(e["event_id"])
            deduped.append(e)

    print(f"\n去重后: {len(deduped)} 条（去掉 {len(all_events)-len(deduped)} 条重复）")

    # 统计
    ended_cnt = sum(1 for e in deduped if e["ended"])
    vol100    = sum(1 for e in deduped if e["volume"] > 100)
    vol1k     = sum(1 for e in deduped if e["volume"] > 1000)
    vol10k    = sum(1 for e in deduped if e["volume"] > 10000)

    print(f"  已结束:        {ended_cnt:,}")
    print(f"  交易量>100:    {vol100:,}")
    print(f"  交易量>1000:   {vol1k:,}")
    print(f"  交易量>10000:  {vol10k:,}")

    # 保存
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for e in deduped:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"\n✓ 已保存 {len(deduped)} 条到 {OUT_FILE}")
    return deduped


if __name__ == "__main__":
    main()
