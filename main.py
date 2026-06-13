"""
main.py - 일일 배치 작업 (매일 새벽 4시 실행)
관심 상품의 최신 가격/재고 상태를 API로 조회하여 DB를 업데이트하고,
변동이 있으면 텔레그램으로 알림을 발송합니다.
"""

import sqlite3
from datetime import datetime
from database import init_db
from domeme_client import DomeameClient
from notifications import notify_status_changes
import os

DB_NAME = "sourcing.db"


def get_tracked_products():
    """DB에서 관심 등록된 상품 목록을 가져옵니다."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE is_tracked = 1")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def update_product_in_db(product_id, site, new_status, new_price):
    """API에서 받아온 최신 상태로 DB를 업데이트합니다."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        UPDATE products
        SET status = ?, supply_price = ?, updated_at = ?
        WHERE product_id = ? AND site = ?
        """,
        (new_status, new_price, current_time, str(product_id), site),
    )
    conn.commit()
    conn.close()


def fetch_latest_product_info(client, product_id, market):
    """
    도매매 API의 getItemView 모드로 단일 상품 최신 정보를 조회합니다.
    API 스펙: https://domeggook.com/ssl/api/?ver=4.1&mode=getItemView&aid=...&no=상품번호
    """
    import requests, json

    params = {
        "ver": "4.1",
        "mode": "getItemView",
        "aid": client.api_key,
        "no": product_id,
        "om": "json",
    }
    try:
        response = requests.get(client.base_url, params=params, timeout=15)
        if response.status_code != 200:
            return None
        data = json.loads(response.text)
        item = data.get("domeggook", {}).get("item", {})
        if not item:
            return None

        def safe(val, default=""):
            if isinstance(val, dict):
                return val.get("#cdata-section", val.get("#text", default))
            return str(val) if val is not None else default

        state_val = safe(item.get("state"), "2")
        stock_val = safe(item.get("stock"), "999")
        status = "N" if state_val in ["3", "4"] or stock_val == "0" else "Y"
        raw_price = safe(item.get("price", "0")).replace(",", "")
        price = int(raw_price) if raw_price.isdigit() else 0
        return {"status": status, "supply_price": price}

    except Exception as e:
        print(f"  [Error] 상품 {product_id} 조회 실패: {e}")
        return None


def run_daily_batch():
    print("=" * 55)
    print(f"  일일 관심 상품 모니터링 배치 시작")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # API 키 가져오기 (환경변수 우선, 없으면 직접 입력)
    api_key = os.environ.get("DOMEGGOOK_API_KEY", "")
    if not api_key:
        print("[Error] API 키가 설정되지 않았습니다. 환경변수 DOMEGGOOK_API_KEY를 설정하세요.")
        return

    client = DomeameClient(api_key=api_key)

    # 1. 관심 상품 목록 불러오기
    tracked = get_tracked_products()
    if not tracked:
        print("[System] 관심 등록된 상품이 없습니다. 배치를 종료합니다.")
        return

    print(f"[System] 관심 상품 {len(tracked)}개 조회 시작...\n")

    changed_items = []

    for product in tracked:
        pid = product["product_id"]
        site = product["site"]
        old_status = product["status"]
        old_price = product["supply_price"]
        market = "supply" if site == "도매매" else "dome"

        print(f"  조회 중: [{site}] {product['name'][:30]}...")

        latest = fetch_latest_product_info(client, pid, market)
        if not latest:
            print(f"  → 조회 실패, 스킵")
            continue

        new_status = latest["status"]
        new_price = latest["supply_price"]
        price_increased = new_price > old_price and old_price > 0

        # 변동이 있을 때만 기록
        if new_status != old_status or price_increased:
            changed_item = {
                "site": site,
                "name": product["name"],
                "status": new_status,
                "supply_price": new_price,
                "price_increased": price_increased,
                "old_price": old_price,
            }
            changed_items.append(changed_item)

            if new_status != old_status:
                print(f"  → ⚠️  상태 변경: {old_status} → {new_status}")
            if price_increased:
                print(f"  → 🔴 가격 인상: {old_price:,}원 → {new_price:,}원")

        # DB 업데이트
        update_product_in_db(pid, site, new_status, new_price)

    print(f"\n[System] 배치 완료. 변동 상품: {len(changed_items)}개")

    # 2. 변동 있으면 텔레그램 알림 발송
    if changed_items:
        print("[System] 텔레그램 알림 발송 중...")
        notify_status_changes(changed_items)
    else:
        print("[System] 변동된 상품이 없어 알림을 생략합니다.")

    print("=" * 55)
    print("  배치 작업 완료")
    print("=" * 55)


if __name__ == "__main__":
    init_db()
    run_daily_batch()
