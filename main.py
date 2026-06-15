"""
main.py v14 — 일일 배치 (새벽 4시 실행 권장)
- 도매매/도매꾹 관심 상품 가격/재고 변동 감지
- 쿠팡 발주서 조회 + 구글 시트 자동 기록
- 텔레그램 알림
"""
import os, sqlite3
from datetime import datetime
from database import init_db
from domeme_client import DomeameClient
from notifications import notify_status_changes, notify_batch_done, send_telegram_message


def _get_secret(key):
    val = os.environ.get(key, "")
    try:
        import streamlit as st
        val = st.secrets.get(key, val)
    except: pass
    return val


def run_batch():
    print("=" * 60)
    print(f"소싱레이더 일일 배치 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    dome_key = _get_secret("DOMEGGOOK_API_KEY")
    if not dome_key:
        print("[오류] DOMEGGOOK_API_KEY 없음"); return

    client = DomeameClient(api_key=dome_key)
    conn   = sqlite3.connect("sourcing.db")
    conn.row_factory = sqlite3.Row
    tracked = [dict(r) for r in conn.execute(
        "SELECT * FROM products WHERE is_tracked=1").fetchall()]
    conn.close()

    changed = []
    for p in tracked:
        pid, site = p["product_id"], p["site"]
        if site == "온채널" or str(pid).startswith("OC_"):
            print(f"  [스킵] {p['name'][:30]}"); continue
        latest = client.fetch_item_detail(pid)
        if not latest: continue
        price_up = latest["supply_price"] > p["supply_price"] > 0
        if latest["status"] != p["status"] or price_up:
            changed.append({**p, **latest, "price_increased": price_up,
                            "old_price": p["supply_price"]})
        conn2 = sqlite3.connect("sourcing.db")
        conn2.execute(
            "UPDATE products SET status=?,supply_price=?,updated_at=? WHERE product_id=? AND site=?",
            (latest["status"], latest["supply_price"],
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(pid), site))
        conn2.commit(); conn2.close()

    notify_status_changes(changed)
    notify_batch_done(len(tracked), len(changed))

    # ── 쿠팡 발주서 조회 + 구글 시트 기록 ──────────────────
    cp_access = _get_secret("COUPANG_ACCESS_KEY")
    cp_secret = _get_secret("COUPANG_SECRET_KEY")
    cp_vendor = _get_secret("COUPANG_VENDOR_ID")
    gs_json   = _get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
    gs_id     = _get_secret("GOOGLE_SHEET_ID")

    if cp_access and cp_secret and cp_vendor:
        try:
            from coupang_client import CoupangClient
            cp = CoupangClient(cp_access, cp_secret, cp_vendor)
            orders = cp.get_orders(status="ACCEPT")
            print(f"[쿠팡] 신규 발주 {len(orders)}건")
            if orders and gs_json and gs_id:
                from sheets_client import SheetsManager
                sm = SheetsManager(gs_json, gs_id)
                sm.log_orders(orders)
            if orders:
                msg = f"📦 쿠팡 신규 발주 {len(orders)}건\n"
                for o in orders[:5]:
                    msg += f"  {o.get('vendorItemName','')[:20]} × {o.get('shippingCount','')}\n"
                send_telegram_message(msg)
        except Exception as e:
            print(f"[쿠팡 배치 오류] {e}")

    print("=" * 60)
    print(f"배치 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    init_db()
    run_batch()
