"""
onchannel_client.py
온채널은 JavaScript 렌더링 기반 SPA로 서버사이드 파싱이 불가능합니다.
대신 온채널 마이페이지 API(비공개 내부 엔드포인트)를 세션 기반으로 호출합니다.
"""
import requests, re, time, json
from bs4 import BeautifulSoup


class OnchannelClient:
    BASE = "https://www.onch3.co.kr"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
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
            # Step 1: 메인 페이지로 세션 쿠키 획득
            self.session.get(f"{self.BASE}/", timeout=10)
            # Step 2: 로그인 POST
            resp = self.session.post(
                f"{self.BASE}/member_action.php",
                data={"mode":"login","id":self.user_id,
                      "passwd":self.password,"save_id":"Y"},
                timeout=15, allow_redirects=True
            )
            # Step 3: 로그인 성공 확인 (마이페이지 접근)
            my = self.session.get(f"{self.BASE}/mypage_main.php", timeout=10)
            if "로그아웃" in my.text or self.user_id in my.text:
                self._logged_in = True
                print("[온채널] 로그인 성공")
                return True
            print("[온채널] 로그인 실패")
            return False
        except Exception as e:
            print(f"[온채널] 로그인 오류: {e}")
            return False

    def fetch_product_list(self, keyword="", page_size=50, max_pages=2) -> list[dict]:
        if not keyword:
            return []
        if not self._logged_in and not self.login():
            return []

        all_results = []
        for pg in range(1, max_pages + 1):
            try:
                # 온채널 데이터센터(상품센터) 검색 엔드포인트
                resp = self.session.get(
                    f"{self.BASE}/goods_search.php",
                    params={"skw": keyword, "page": pg, "sm": "goods_name"},
                    timeout=15
                )
                if resp.status_code != 200:
                    break
                resp.encoding = "utf-8"

                items = self._parse(resp.text)
                if not items:
                    # 대안 엔드포인트 시도
                    resp2 = self.session.get(
                        f"{self.BASE}/index_goods_list.php",
                        params={"skw": keyword, "page": pg},
                        timeout=15
                    )
                    resp2.encoding = "utf-8"
                    items = self._parse(resp2.text)

                if not items:
                    break

                all_results.extend(items)
                print(f"[온채널] pg={pg} → {len(items)}개")
                if len(items) < 8 or len(all_results) >= page_size:
                    break
                if pg < max_pages:
                    time.sleep(0.5)
            except Exception as e:
                print(f"[온채널] 검색 오류: {e}")
                break

        return all_results[:page_size]

    def _parse(self, html: str) -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # 온채널 상품 목록: 여러 셀렉터 패턴 시도
            items = (
                soup.select("ul.goods_list > li")
                or soup.select("div.data_center_wrap li.item")
                or soup.select(".goods_list_wrap li")
                or soup.select("li.goods_item")
                or soup.select("div[class*='goods'] li")
                or soup.select("ul[class*='list'] li[class*='item']")
            )

            # 디버그: 파싱 시도한 li 수 로깅
            all_li = soup.select("li")
            print(f"[온채널 파싱] 총 li={len(all_li)}개, 매칭 item={len(items)}개")

            for item in items:
                try:
                    # 상품명
                    name_el = (
                        item.select_one(".goods_name, .item_name, .name")
                        or item.select_one("a.goods_link")
                        or item.select_one("strong")
                        or item.select_one("a")
                    )
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    if len(name) < 2 or name.isdigit():
                        continue

                    # 가격
                    price_el = item.select_one(
                        ".goods_price, .price, [class*='price']"
                    )
                    price = 0
                    if price_el:
                        nums = re.sub(r"[^0-9]", "", price_el.get_text())
                        price = int(nums) if nums else 0

                    # 배송비
                    deli_el = item.select_one(
                        ".delivery, [class*='deli'], [class*='ship'], [class*='delivery']"
                    )
                    delivery = 3000
                    if deli_el:
                        dt = deli_el.get_text(strip=True)
                        if "무료" in dt:
                            delivery = 0
                        else:
                            dn = re.sub(r"[^0-9]", "", dt)
                            delivery = int(dn) if dn else 3000

                    # 업체 등급/평점
                    grade_el = item.select_one(
                        "[class*='grade'], [class*='rating'], [class*='level'], .seller_grade"
                    )
                    seller_grade = grade_el.get_text(strip=True) if grade_el else "- 미확인"

                    # 상품 ID
                    link_el = item.select_one("a[href]")
                    href = link_el["href"] if link_el else ""
                    pid_m = re.search(r"num=(\d+)|vnum=(\d+)|no=(\d+)|goods_no=(\d+)", href)
                    pid = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
                    if not pid:
                        continue

                    results.append({
                        "site": "온채널", "product_id": f"OC_{pid}",
                        "name": name, "supply_price": price,
                        "delivery_fee": delivery, "status": "Y",
                        "seller_grade": seller_grade,
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"[온채널 파싱 오류] {e}")
        return results
