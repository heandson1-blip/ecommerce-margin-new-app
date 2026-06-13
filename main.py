"""
main.py — 일일 배치 작업 (매일 새벽 04:00 실행 권장)
관심 상품의 최신 가격/재고를 API로 확인하고 DB를 갱신합니다.
변동이 있으면 텔레그램으로 즉시 알림을 보냅니다.

실행 방법:
  python main.py

자동화 (Linux cron):
  0 4 * * * /usr/bin/python3 /path/to/main.py >> /var/log/sourcing.log 2>&1
"""

import os
import sqlite3
from datetime import datetime

from database import init_db
from domeme_client import DomeameClient
from notifications import notify_status_changes, notify_batch_done

DB_NAME = "sourcing.db"


def get_tracked() -> list[dict]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute("SELECT * FROM products WHERE is_tracked = 1")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_db(product_id: str, site: str, status: str, price: int) -> None:
    conn = sqlite3.connect(DB_NAME)
    conn.execute(
        "UPDATE products SET status=?, supply_price=?, updated_at=? WHERE product_id=? AND site=?",
        (status, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(product_id), site),
    )
    conn.commit()
    conn.close()


def run_batch() -> None:
    print("=" * 60)
    print(f"  소싱레이더 일일 배치 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    api_key = os.environ.get("DOMEGGOOK_API_KEY", "")
    if not api_key:
        # Streamlit secrets fallback (서버 환경용)
        try:
            import streamlit as st
            api_key = st.secrets.get("DOMEGGOOK_API_KEY", "")
        except Exception:
            pass

    if not api_key:
        print("[오류] DOMEGGOOK_API_KEY가 설정되지 않았습니다.")
        return

    client  = DomeameClient(api_key=api_key)
    tracked = get_tracked()

    if not tracked:
        print("[완료] 관심 상품이 없습니다.")
        notify_batch_done(0, 0)
        return

    print(f"[시작] 관심 상품 {len(tracked)}개 상태 점검\n")
    changed = []

    for p in tracked:
        pid       = p["product_id"]
        site      = p["site"]
        old_st    = p["status"]
        old_price = p["supply_price"]
        market    = "supply" if site == "도매매" else "dome"

        print(f"  [{site}] {p['name'][:35]}...")
        latest = client.fetch_item_detail(pid)

        if not latest:
            print("    → 조회 실패, 스킵")
            continue

        new_st    = latest["status"]
        new_price = latest["supply_price"]
        price_up  = new_price > old_price > 0

        if new_st != old_st:
            print(f"    → 상태 변경: {old_st} → {new_st}")
        if price_up:
            print(f"    → 가격 인상: {old_price:,} → {new_price:,}원")

        if new_st != old_st or price_up:
            changed.append({
                "site": site, "name": p["name"],
                "status": new_st, "supply_price": new_price,
                "price_increased": price_up, "old_price": old_price,
            })

        update_db(pid, site, new_st, new_price)

    print(f"\n[완료] 변동 상품: {len(changed)}개")
    notify_status_changes(changed)
    notify_batch_done(len(tracked), len(changed))
    print("=" * 60)


if __name__ == "__main__":
    init_db()
    run_batch()
