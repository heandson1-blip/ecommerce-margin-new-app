"""
notifications.py - 텔레그램 알림 발송 모듈
토큰과 채팅방 ID는 환경변수 또는 Streamlit Secrets에서 불러옵니다.
"""

import requests
import os


def _get_credentials():
    """텔레그램 토큰과 채팅방 ID를 환경변수에서 가져옵니다."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Streamlit 환경에서는 st.secrets에서 가져오기 시도
    if not token or not chat_id:
        try:
            import streamlit as st
            token = st.secrets.get("TELEGRAM_BOT_TOKEN", token)
            chat_id = st.secrets.get("TELEGRAM_CHAT_ID", chat_id)
        except Exception:
            pass

    return token, chat_id


def send_telegram_message(message: str) -> bool:
    """
    텔레그램으로 메시지를 전송합니다.
    반환값: 성공 시 True, 실패 시 False
    """
    token, chat_id = _get_credentials()

    if not token or not chat_id or "입력하세요" in token:
        print("[System] 텔레그램 토큰 또는 채팅방 ID가 설정되지 않아 알림을 건너뜁니다.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("[System] 📱 텔레그램 알림 발송 완료.")
        return True
    except requests.exceptions.ConnectionError:
        print("[Error] 텔레그램 서버에 연결할 수 없습니다. 네트워크를 확인하세요.")
    except requests.exceptions.Timeout:
        print("[Error] 텔레그램 요청 시간이 초과되었습니다.")
    except requests.exceptions.HTTPError as e:
        print(f"[Error] 텔레그램 API 오류: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"[Error] 텔레그램 알림 발송 중 예외 발생: {e}")
    return False


def notify_status_changes(changed_items: list) -> None:
    """
    변동 상품 목록을 받아 텔레그램으로 리포트를 발송합니다.
    changed_items: [{'site', 'name', 'status', 'supply_price', 'price_increased', 'old_price'}, ...]
    """
    if not changed_items:
        print("[System] 변동된 상품이 없어 알림을 생략합니다.")
        return

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    oos_items = [i for i in changed_items if i.get("status") == "N"]
    price_items = [i for i in changed_items if i.get("price_increased")]

    message = f"🚨 <b>[소싱 자동화 리포트]</b>\n"
    message += f"📅 {now} 기준 변동 알림\n"
    message += "─" * 25 + "\n\n"

    if oos_items:
        message += f"❌ <b>품절 전환 ({len(oos_items)}건)</b>\n"
        for item in oos_items:
            message += f"  • {item['name'][:25]} ({item['site']})\n"
        message += "\n"

    if price_items:
        message += f"🔴 <b>공급가 인상 ({len(price_items)}건)</b>\n"
        for item in price_items:
            old = item.get("old_price", 0)
            new = item.get("supply_price", 0)
            diff = new - old
            message += f"  • {item['name'][:20]} ({item['site']})\n"
            message += f"    {old:,}원 → {new:,}원 (+{diff:,}원)\n"
        message += "\n"

    message += "💡 <i>시스템에 접속하여 마진을 다시 확인하세요.</i>"

    send_telegram_message(message)


def notify_batch_summary(total: int, changed: int) -> None:
    """배치 완료 후 요약 알림 (변동 없어도 발송 가능)."""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if changed == 0:
        message = f"✅ <b>[배치 완료]</b> {now}\n전체 {total}개 상품 점검 완료. 변동 없음."
    else:
        message = f"⚠️ <b>[배치 완료]</b> {now}\n전체 {total}개 중 <b>{changed}개</b> 변동 감지됨."

    send_telegram_message(message)


# 독립 실행 테스트
if __name__ == "__main__":
    test_data = [
        {
            "site": "도매매",
            "name": "프리미엄 방수 백팩 30L",
            "status": "N",
            "supply_price": 18000,
            "price_increased": False,
            "old_price": 18000,
        },
        {
            "site": "도매꾹",
            "name": "무선 블루투스 이어폰",
            "status": "Y",
            "supply_price": 28000,
            "price_increased": True,
            "old_price": 24000,
        },
    ]
    print("텔레그램 알림 테스트를 실행합니다...")
    notify_status_changes(test_data)
