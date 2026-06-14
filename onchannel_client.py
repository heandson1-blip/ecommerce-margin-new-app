"""
onchannel_client.py v13
======================
온채널(www.onch3.co.kr) 접근 현황:
- Streamlit Cloud 무료 플랜: 네트워크 egress 제한으로 외부 사이트 접근 가능
- 단, 온채널 서버가 클라우드 호스팅 IP를 자체 차단 (403)
- ID/PW 로그인 요청 자체가 차단되므로 크롤링 불가

해결책:
1. Streamlit Cloud → Settings → Network → Egress에 www.onch3.co.kr 추가 (유료 플랜)
2. 또는 로컬 PC에서 직접 실행

현재: 사용 불가 안내 메시지만 제공
"""


class OnchannelClient:
    """온채널 클라이언트 — 현재 클라우드 환경에서 사용 불가"""

    UNAVAILABLE_MSG = (
        "온채널은 현재 클라우드 서버 환경에서 접근이 차단됩니다.\n"
        "온채널 상품은 직접 www.onch3.co.kr에서 확인해주세요."
    )

    def __init__(self, user_id="", password=""):
        self.user_id    = user_id
        self.password   = password
        self.last_error = self.UNAVAILABLE_MSG
        self._logged_in = False

    def login(self) -> bool:
        self.last_error = self.UNAVAILABLE_MSG
        return False

    def fetch_product_list(self, keyword="", page_size=50, max_pages=2) -> list[dict]:
        """항상 빈 리스트 반환 — raise 없음"""
        self.last_error = self.UNAVAILABLE_MSG
        return []
