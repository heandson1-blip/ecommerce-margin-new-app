"""
onchannel_client.py
온채널은 SPA(Vue.js) 구조로 서버사이드 HTML 파싱이 근본적으로 불가합니다.
현재 구현: 로그인 세션 + 파싱 시도 (성공률 제한적)
향후 방안: Playwright 브라우저 자동화 (별도 서버 필요)
"""
import requests, re, time
from bs4 import BeautifulSoup


class OnchannelClient:
    BASE = "https://www.onch3.co.kr"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.onch3.co.kr/",
    }

    def __init__(self, user_id="", password=""):
        self.user_id  = user_id
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._logged_in = False

    def login(self) -> bool:
        if not self.user_id or not self.password:
            print("[온채널] ID/PW 미설정")
            return False
        try:
            self.session.get(f"{self.BASE}/", timeout=10)
            resp = self.session.post(
                f"{self.BASE}/member_action.php",
                data={"mode":"login","id":self.user_id,"passwd":self.password,"save_id":"Y"},
                timeout=15, allow_redirects=True
            )
            check = self.session.get(f"{self.BASE}/mypage_main.php", timeout=10)
            if "로그아웃" in check.text or self.user_id in check.text:
                self._logged_in = True
                print("[온채널] 로그인 성공")
                return True
            print("[온채널] 로그인 실패 — ID/PW 확인 필요")
            return False
        except Exception as e:
            print(f"[온채널] 로그인 오류: {e}")
            return False

    def fetch_product_list(self, keyword="", page_size=50, max_pages=2) -> list[dict]:
        """
        온채널 상품 검색.
        ※ SPA 구조로 완전한 파싱은 제한적. 로그인 후 서버사이드 렌더링 일부 데이터 수집.
        """
        if not keyword:
            return []
        if not self._logged_in and not self.login():
            return []

        all_results = []
        # 여러 검색 엔드포인트 시도
        endpoints = [
            f"{self.BASE}/goods_search.php",
            f"{self.BASE}/data_center.php",
            f"{self.BASE}/index_goods_list.php",
        ]

        for endpoint in endpoints:
            for pg in range(1, max_pages + 1):
                try:
                    resp = self.session.get(
                        endpoint,
                        params={"skw": keyword, "page": pg, "sm": "goods_name"},
                        timeout=15
                    )
                    if resp.status_code != 200:
                        continue
                    resp.encoding = "utf-8"
                    items = self._parse(resp.text)
                    if items:
                        all_results.extend(items)
                        print(f"[온채널] {endpoint.split('/')[-1]} pg={pg} → {len(items)}개")
                        if len(items) < 8 or len(all_results) >= page_size:
                            break
                        if pg < max_pages:
                            time.sleep(0.5)
                except Exception as e:
                    print(f"[온채널] {endpoint}: {e}")
                    continue

            if all_results:
                break

        if not all_results:
            print("[온채널] 모든 엔드포인트에서 결과 없음 — SPA 구조로 파싱 불가")

        return all_results[:page_size]

    def _parse(self, html: str) -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            items = (
                soup.select("ul.goods_list > li")
                or soup.select("div.goods_list_wrap li")
                or soup.select("li.goods_item")
                or soup.select(".data_center_wrap li.item")
                or soup.select("li[class*='item']")
            )

            all_li = soup.select("li")
            print(f"[온채널 파싱] li={len(all_li)}개 / 매칭={len(items)}개")

            for item in items:
                try:
                    name_el = (
                        item.select_one(".goods_name,.item_name,.name")
                        or item.select_one("a.goods_link")
                        or item.select_one("strong")
                        or item.select_one("a")
                    )
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    if len(name) < 2:
                        continue

                    price_el = item.select_one(".goods_price,.price,[class*='price']")
                    price = 0
                    if price_el:
                        nums = re.sub(r"[^0-9]", "", price_el.get_text())
                        price = int(nums) if nums else 0

                    deli_el = item.select_one(".delivery,[class*='deli'],[class*='ship']")
                    delivery = 3000
                    if deli_el:
                        dt = deli_el.get_text(strip=True)
                        delivery = 0 if "무료" in dt else int(re.sub(r"[^0-9]","",dt) or 3000)

                    grade_el = item.select_one("[class*='grade'],[class*='rating'],[class*='level'],.seller_grade")
                    seller_grade = grade_el.get_text(strip=True) if grade_el else "- 온채널"

                    link_el = item.select_one("a[href]")
                    href = link_el["href"] if link_el else ""
                    pid_m = re.search(r"num=(\d+)|vnum=(\d+)|no=(\d+)", href)
                    pid = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
                    if not pid:
                        continue

                    results.append({
                        "site":"온채널","product_id":f"OC_{pid}",
                        "name":name,"supply_price":price,
                        "delivery_fee":delivery,"status":"Y",
                        "seller_grade":seller_grade,
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"[온채널 파싱 오류] {e}")
        return results
