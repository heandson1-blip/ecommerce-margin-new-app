"""
notifications.py — 텔레그램 알림 모듈
TELEGRAM_CHAT_IDS (콤마 구분 복수 ID) 또는 TELEGRAM_CHAT_ID (단일) 지원
"""
import os
import requests
import time


def _get_credentials():
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    chat_ids_raw = os.environ.get("TELEGRAM_CHAT_IDS", "")

    try:
        import streamlit as st
        token        = st.secrets.get("TELEGRAM_BOT_TOKEN", token)
        chat_id      = st.secrets.get("TELEGRAM_CHAT_ID", chat_id)
        chat_ids_raw = st.secrets.get("TELEGRAM_CHAT_IDS", chat_ids_raw)
    except Exception:
        pass

    # TELEGRAM_CHAT_IDS (복수) 우선, 없으면 TELEGRAM_CHAT_ID 사용
    if chat_ids_raw:
        ids = [cid.strip() for cid in str(chat_ids_raw).split(",") if cid.strip()]
    elif chat_id:
        ids = [chat_id.strip()]
    else:
        ids = []

    return token, ids


def send_telegram_message(message: str) -> bool:
    """
    텔레그램 메시지 전송.
    TELEGRAM_CHAT_IDS에 여러 ID가 있으면 모두에게 전송.
    모두 성공 시 True, 하나라도 실패 시 False.
    """
    token, ids = _get_credentials()

    if not token or not ids:
        print("[Telegram] 토큰 또는 채팅방 ID 미설정")
        return False

    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    success = True

    for chat_id in ids:
        payload = {
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f"[Telegram] ✅ 발송 완료 → chat_id={chat_id}")
            else:
                print(f"[Telegram] ❌ 실패 chat_id={chat_id}: {resp.status_code} {resp.text[:100]}")
                success = False
        except Exception as e:
            print(f"[Telegram] 예외 chat_id={chat_id}: {e}")
            success = False

        if len(ids) > 1:
            time.sleep(0.3)  # 다중 전송 시 딜레이

    return success


def notify_status_changes(changed_items: list) -> None:
    if not changed_items:
        return
    from datetime import datetime
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    oos  = [i for i in changed_items if i.get("status") == "N"]
    priced = [i for i in changed_items if i.get("price_increased")]

    msg = f"🚨 <b>[소싱레이더] 변동 알림</b>\n📅 {now}\n\n"
    if oos:
        msg += f"❌ <b>품절 전환 {len(oos)}건</b>\n"
        for i in oos:
            msg += f"  {i['name'][:28]} ({i['site']})\n"
    if priced:
        msg += f"🔴 <b>공급가 인상 {len(priced)}건</b>\n"
        for i in priced:
            old, new = i.get("old_price",0), i.get("supply_price",0)
            msg += f"  {i['name'][:22]} {old:,}원 → {new:,}원\n"
    msg += "\n💡 <i>소싱레이더에 접속하여 확인하세요.</i>"
    send_telegram_message(msg)


def notify_batch_done(total: int, changed: int) -> None:
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if changed == 0:
        msg = f"✅ <b>[소싱레이더]</b> {now}\n전체 {total}개 점검 완료. 변동 없음."
    else:
        msg = f"⚠️ <b>[소싱레이더]</b> {now}\n전체 {total}개 중 <b>{changed}개</b> 변동 감지."
    send_telegram_message(msg)


if __name__ == "__main__":
    print("텔레그램 테스트...")
    ok = send_telegram_message("✅ 소싱레이더 다중 수신자 테스트!")
    print("결과:", "성공" if ok else "실패")
