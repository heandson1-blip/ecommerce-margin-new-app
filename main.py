"""
main.py — 일일 배치 작업 (매일 새벽 04:00 실행 권장)
분석 보고서 보완: 온채널 상품 스킵 처리 추가
"""
import os
import sqlite3
from datetime import datetime

from database import init_db
from domeme_client import DomeameClient
from notifications import notify_status_changes, notify_batch_done

DB_NAME = "sourcing.db"


def get_tracked():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()
    cur.execute("SELECT * FROM products WHERE is_tracked = 1")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_db(product_id, site, status, price):
    conn = sqlite3.connect(DB_NAME)
    conn.execute(
        "UPDATE products SET status=?, supply_price=?, updated_at=? WHERE product_id=? AND site=?",
        (status, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(product_id), site),
    )
    conn.commit()
    conn.close()


def run_batch():
    print("=" * 60)
    print(f"  소싱레이더 일일 배치 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    api_key = os.environ.get("DOMEGGOOK_API_KEY", "")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("DOMEGGOOK_API_KEY", "")
        except Exception:
            pass

    if not api_key:
        print("[오류] DOMEGGOOK_API_KEY 미설정")
        return

    client  = DomeameClient(api_key=api_key)
    tracked = get_tracked()

    if not tracked:
        print("[완료] 관심 상품 없음")
        notify_batch_done(0, 0)
        return

    print(f"[시작] 관심 상품 {len(tracked)}개 점검\n")
    changed = []
    skipped = 0

    for p in tracked:
        pid  = p["product_id"]
        site = p["site"]

        # ★ 분석 보고서 보완: 온채널 상품 스킵
        if site == "온채널" or str(pid).startswith("OC_"):
            print(f"  [온채널] {p['name'][:35]}... → 클라우드 배치 조회 불가, 스킵")
            skipped += 1
            continue

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

    print(f"\n[완료] 변동: {len(changed)}개 / 스킵(온채널): {skipped}개")
    notify_status_changes(changed)
    notify_batch_done(len(tracked), len(changed))
    print("=" * 60)


if __name__ == "__main__":
    init_db()
    run_batch()
