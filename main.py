"""main.py — 일일 배치 (새벽 4시 실행)"""
import os, sqlite3
from datetime import datetime
from database import init_db
from domeme_client import DomeameClient
from notifications import notify_status_changes, notify_batch_done

def run_batch():
    api_key = os.environ.get("DOMEGGOOK_API_KEY","")
    try:
        import streamlit as st
        api_key = st.secrets.get("DOMEGGOOK_API_KEY", api_key)
    except: pass
    if not api_key: print("[오류] API 키 없음"); return
    client = DomeameClient(api_key=api_key)
    conn = sqlite3.connect("sourcing.db")
    conn.row_factory = sqlite3.Row
    tracked = [dict(r) for r in conn.execute("SELECT * FROM products WHERE is_tracked=1").fetchall()]
    conn.close()
    changed = []
    for p in tracked:
        pid, site = p["product_id"], p["site"]
        if site == "온채널" or str(pid).startswith("OC_"):
            print(f"  [스킵] {p['name'][:30]}"); continue
        latest = client.fetch_item_detail(pid)
        if not latest: continue
        if latest["status"] != p["status"] or latest["supply_price"] > p["supply_price"] > 0:
            changed.append({**p, **latest, "price_increased": latest["supply_price"] > p["supply_price"]})
        conn2 = sqlite3.connect("sourcing.db")
        conn2.execute("UPDATE products SET status=?,supply_price=?,updated_at=? WHERE product_id=? AND site=?",
            (latest["status"], latest["supply_price"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(pid), site))
        conn2.commit(); conn2.close()
    notify_status_changes(changed)
    notify_batch_done(len(tracked), len(changed))

if __name__ == "__main__":
    init_db(); run_batch()
