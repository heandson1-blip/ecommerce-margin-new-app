"""
notifications.py — 텔레그램 알림 모듈
토큰/채팅방 ID는 환경변수 또는 Streamlit Secrets에서 자동으로 불러옵니다.
"""

import os
import requests
from datetime import datetime


def _creds() -> tuple[str, str]:
    """토큰과 채팅방 ID를 환경변수 → Streamlit Secrets 순서로 조회."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        try:
            import streamlit as st
            token   = st.secrets.get("TELEGRAM_BOT_TOKEN", token)
            chat_id = st.secrets.get("TELEGRAM_CHAT_ID", chat_id)
        except Exception:
            pass

    return token, chat_id


def _is_placeholder(val: str) -> bool:
    return not val or any(kw in val for kw in ["입력", "여기에", "your", "TOKEN"])


def send_telegram_message(message: str, retry: int = 2) -> bool:
    """
    텔레그램 메시지 전송. 성공 시 True, 실패 시 False.
    retry: 실패 시 재시도 횟수
    """
    token, chat_id = _creds()

    if _is_placeholder(token) or _is_placeholder(chat_id):
        print("[Telegram] 토큰 또는 채팅방 ID가 설정되지 않아 알림을 건너뜁니다.")
        return False

    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    for attempt in range(1, retry + 2):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f"[Telegram] ✅ 발송 완료 (시도 {attempt}회)")
                return True
            elif resp.status_code == 400:
                print(f"[Telegram] ❌ 잘못된 요청: {resp.text}")
                return False  # 재시도해도 의미 없음
            else:
                print(f"[Telegram] HTTP {resp.status_code}, 재시도 {attempt}...")
        except requests.exceptions.Timeout:
            print(f"[Telegram] 타임아웃 (시도 {attempt})")
        except requests.exceptions.ConnectionError:
            print(f"[Telegram] 연결 실패 (시도 {attempt})")
        except Exception as e:
            print(f"[Telegram] 예외: {e}")

    return False


def notify_status_changes(changed_items: list) -> None:
    """품절·가격인상 변동 목록을 텔레그램으로 발송."""
    if not changed_items:
        return

    now     = datetime.now().strftime("%Y-%m-%d %H:%M")
    oos     = [i for i in changed_items if i.get("status") == "N"]
    priced  = [i for i in changed_items if i.get("price_increased")]

    msg = f"🚨 <b>[소싱레이더] 변동 알림</b>\n📅 {now}\n{'─'*20}\n\n"

    if oos:
        msg += f"❌ <b>품절 전환 {len(oos)}건</b>\n"
        for i in oos:
            msg += f"  • {i['name'][:28]} ({i['site']})\n"
        msg += "\n"

    if priced:
        msg += f"🔴 <b>공급가 인상 {len(priced)}건</b>\n"
        for i in priced:
            old, new = i.get("old_price", 0), i.get("supply_price", 0)
            msg += f"  • {i['name'][:22]} ({i['site']})\n"
            msg += f"    {old:,}원 → {new:,}원 (<b>+{new-old:,}원</b>)\n"

    msg += "\n💡 <i>소싱레이더에 접속하여 마진을 다시 확인하세요.</i>"
    send_telegram_message(msg)


def notify_batch_done(total: int, changed: int) -> None:
    """배치 완료 요약 알림."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if changed == 0:
        msg = f"✅ <b>[소싱레이더] 배치 완료</b>\n📅 {now}\n전체 {total}개 점검 완료. 변동 없음."
    else:
        msg = f"⚠️ <b>[소싱레이더] 배치 완료</b>\n📅 {now}\n전체 {total}개 중 <b>{changed}개</b> 변동 감지됨."
    send_telegram_message(msg)


# ── 독립 실행 테스트 ──────────────────────────
if __name__ == "__main__":
    print("텔레그램 연동 테스트...")
    ok = send_telegram_message("✅ 소싱레이더 텔레그램 연동 테스트 성공!")
    print("결과:", "성공" if ok else "실패 — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수를 확인하세요.")
