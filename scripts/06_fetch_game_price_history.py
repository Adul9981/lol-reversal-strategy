"""
Step 6: 采集 Game N Winner 市场的价格历史

输入: data/game_winner_markets/game_winner_markets.json
输出: data/game_winner_markets/game_price_history/{token_id}.json

只采集 LCK / LPL / LEC / LCS 联赛
断点续传，8线程并发
"""

import json, time, urllib3
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings()

BASE      = Path(__file__).parent.parent
MARKETS_FILE = BASE / "data/game_winner_markets/game_winner_markets.json"
OUT_DIR   = BASE / "data/game_winner_markets/game_price_history"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CLOB_BASE   = "https://clob.polymarket.com"
TARGET_LEAGUES = {"LCK", "LPL", "LEC", "LCS"}
MIN_POINTS  = 5
THREADS     = 8

session = requests.Session()
session.verify = False


def fetch_history(token_id: str) -> list:
    out_file = OUT_DIR / f"{token_id}.json"
    if out_file.exists():
        return []  # already done

    for attempt in range(5):
        try:
            r = session.get(
                f"{CLOB_BASE}/prices-history",
                params={"market": token_id, "interval": "max", "fidelity": 1},
                timeout=20,
            )
            if r.status_code == 200:
                hist = r.json().get("history", [])
                out_file.write_text(json.dumps(hist))
                return hist
            time.sleep(1)
        except Exception:
            time.sleep(2 ** attempt)
    return []


def main():
    with open(MARKETS_FILE) as f:
        markets = json.load(f)

    # Filter to target leagues only
    targets = [m for m in markets if m["league"] in TARGET_LEAGUES]
    print(f"Target markets (LCK/LPL/LEC/LCS): {len(targets)}")

    already_done = sum(
        1 for m in targets
        if (OUT_DIR / f"{m['token_0']}.json").exists()
    )
    print(f"Already fetched: {already_done}")
    print(f"To fetch: {len(targets) - already_done}")

    ok = already_done
    empty = 0
    err = 0
    total = len(targets)

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(fetch_history, m["token_0"]): m for m in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            hist = fut.result()
            if hist is None:
                err += 1
            elif len(hist) >= MIN_POINTS:
                ok += 1
            else:
                empty += 1

            if i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] ok={ok} empty={empty} err={err}")

    print(f"\n完成: ok={ok} empty={empty} err={err}")
    print(f"有效价格历史: {ok} 个市场")


if __name__ == "__main__":
    main()
