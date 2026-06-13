"""
onchannel_client.py — 온채널 상품 검색 클라이언트
온채널은 로그인 후에만 상품 검색이 가능합니다.
ONCHANNEL_ID / ONCHANNEL_PW 를 Streamlit Secrets에 등록하세요.
"""

import requests
from bs4 import BeautifulSoup
import re
import time


class OnchannelClient:
    BASE_URL   = "https://www.onch3.co.kr"
    LOGIN_URL  = "https://www.onch3.co.kr/member_action.php"
    SEARCH_URL = "https://www.onch3.co.kr/goods_search.php"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.onch3.co.kr/",
    }

    def __init__(self, user_id: str = "", password: str = ""):
        self.user_id  = user_id
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._logged_in = False

    def login(self) -> bool:
        """온채널 로그인. 성공 시 True."""
        if not self.user_id or not self.password:
            print("[온채널] ID/PW 미설정 — Secrets에 ONCHANNEL_ID / ONCHANNEL_PW 를 등록하세요.")
            return False
        try:
            payload = {
                "mode":   "login",
                "id":     self.user_id,
                "passwd": self.password,
            }
            resp = self.session.post(self.LOGIN_URL, data=payload, timeout=15, allow_redirects=True)
            # 로그인 성공 여부: 마이페이지 관련 쿠키 또는 리다이렉트 확인
            if "PHPSESSID" in self.session.cookies or resp.url != self.LOGIN_URL:
                # 추가 확인: 로그아웃 링크가 페이지에 있으면 로그인 성공
                if "로그아웃" in resp.text or "logout" in resp.text.lower():
                    self._logged_in = True
                    print("[온채널] 로그인 성공")
                    return True
            print("[온채널] 로그인 실패 — ID/PW를 확인하세요.")
            return False
        except Exception as e:
            print(f"[온채널] 로그인 오류: {e}")
            return False

    def fetch_product_list(
        self,
        keyword: str = "",
        page_size: int = 50,
        max_pages: int = 2,
    ) -> list[dict]:
        """온채널 상품 키워드 검색."""
        if not keyword:
            print("[온채널] 키워드를 입력하세요.")
            return []

        if not self._logged_in:
            if not self.login():
                return []

        all_results = []
        for pg in range(1, max_pages + 1):
            try:
                params = {"skw": keyword, "page": pg, "view_type": "list"}
                resp   = self.session.get(self.SEARCH_URL, params=params, timeout=15)
                if resp.status_code != 200:
                    print(f"[온채널] HTTP {resp.status_code} (pg={pg})")
                    break
                resp.encoding = "utf-8"
                items = self._parse(resp.text)
                if not items:
                    break
                all_results.extend(items)
                print(f"[온채널] pg={pg} → {len(items)}개 (누적 {len(all_results)}개)")
                if len(items) < 10:
                    break
                if pg < max_pages:
                    time.sleep(0.5)
                if len(all_results) >= page_size:
                    break
            except Exception as e:
                print(f"[온채널] 검색 오류 (pg={pg}): {e}")
                break

        return all_results[:page_size]

    def _parse(self, html: str) -> list[dict]:
        results = []
        try:
            soup  = BeautifulSoup(html, "html.parser")

            # 온채널 상품 목록 셀렉터 (여러 패턴 시도)
            items = (
                soup.select("ul.goods_list > li")
                or soup.select("div.goods_list_wrap li")
                or soup.select("li.goods_item")
                or soup.select("[class*='goods_list'] li")
            )

            for item in items:
                try:
                    # 상품명
                    name_el = (
                        item.select_one(".goods_name")
                        or item.select_one(".name")
                        or item.select_one("a > span")
                        or item.select_one("strong")
                    )
                    name = name_el.get_text(strip=True) if name_el else ""
                    if not name or len(name) < 2:
                        continue

                    # 가격
                    price_el = (
                        item.select_one(".goods_price")
                        or item.select_one(".price")
                        or item.select_one("[class*='price']")
                    )
                    price_txt = price_el.get_text(strip=True) if price_el else "0"
                    price     = int(re.sub(r"[^0-9]", "", price_txt) or 0)

                    # 배송비
                    delivery_el = (
                        item.select_one(".delivery")
                        or item.select_one("[class*='delivery']")
                        or item.select_one("[class*='ship']")
                    )
                    if delivery_el:
                        d_txt    = delivery_el.get_text(strip=True)
                        d_digits = re.sub(r"[^0-9]", "", d_txt)
                        delivery = int(d_digits) if d_digits else 3000
                        if "무료" in d_txt:
                            delivery = 0
                    else:
                        delivery = 3000

                    # 상품 ID
                    link_el = item.select_one("a[href]")
                    href    = link_el["href"] if link_el else ""
                    pid_m   = re.search(r"num=(\d+)|no=(\d+)|goods_no=(\d+)|vnum=(\d+)", href)
                    pid     = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
                    if not pid:
                        continue

                    results.append({
                        "site":         "온채널",
                        "product_id":   f"OC_{pid}",
                        "name":         name,
                        "supply_price": price,
                        "delivery_fee": delivery,
                        "status":       "Y",
                    })
                except Exception:
                    continue

        except Exception as e:
            print(f"[온채널 파싱 오류] {e}")
        return results
