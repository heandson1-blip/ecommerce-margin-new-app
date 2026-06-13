"""
onchannel_client.py
온채널 상품 검색: 로그인 세션 + HTML 크롤링 병행
Secrets: ONCHANNEL_ID / ONCHANNEL_PW
"""
import requests, re, time, json
from bs4 import BeautifulSoup


class OnchannelClient:
    BASE = "https://www.onch3.co.kr"
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    def __init__(self, user_id="", password=""):
        self.user_id  = user_id
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._logged_in = False

    # ── 로그인 ──────────────────────────────────────────────────
    def login(self) -> bool:
        if not self.user_id or not self.password:
            print("[온채널] ID/PW 미설정 — Secrets에 ONCHANNEL_ID / ONCHANNEL_PW 등록 필요")
            return False
        try:
            # 1) 메인 페이지 → 세션 쿠키 획득
            self.session.get(f"{self.BASE}/", timeout=10)
            time.sleep(0.3)
            # 2) 로그인 POST
            self.session.post(
                f"{self.BASE}/member_action.php",
                data={"mode":"login","id":self.user_id,
                      "passwd":self.password,"save_id":"Y","url":"/"},
                timeout=15, allow_redirects=True
            )
            # 3) 마이페이지로 성공 확인
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

    # ── 상품 검색 ────────────────────────────────────────────────
    def fetch_product_list(self, keyword="", page_size=50, max_pages=2) -> list[dict]:
        if not keyword:
            return []
        # 로그인 시도 (실패해도 비로그인 크롤링으로 대체)
        if not self._logged_in:
            self.login()

        all_results = []
        # 시도할 검색 URL 목록 (로그인/비로그인 모두 시도)
        search_urls = [
            f"{self.BASE}/goods_search.php",
            f"{self.BASE}/data_center.php",
            f"{self.BASE}/index_goods_list.php",
            f"{self.BASE}/goods_list.php",
        ]

        for url in search_urls:
            for pg in range(1, max_pages + 1):
                try:
                    resp = self.session.get(
                        url, params={"skw": keyword, "page": pg, "sm": "goods_name"},
                        timeout=15
                    )
                    if resp.status_code != 200:
                        continue
                    resp.encoding = "utf-8"

                    # HTML 크롤링으로 파싱
                    items = self._crawl(resp.text, resp.url)
                    if not items:
                        print(f"[온채널] {url.split('/')[-1]} pg={pg}: 파싱 결과 없음")
                        continue

                    all_results.extend(items)
                    print(f"[온채널] {url.split('/')[-1]} pg={pg} → {len(items)}개 (누적 {len(all_results)})")

                    if len(items) < 5 or len(all_results) >= page_size:
                        break
                    time.sleep(0.5)
                except Exception as e:
                    print(f"[온채널] {url}: {e}")
                    continue

            if all_results:
                break  # 한 URL에서 결과가 나오면 중단

        if not all_results:
            print("[온채널] 모든 엔드포인트에서 결과 없음 (JS 렌더링 필요 가능성)")

        return all_results[:page_size]

    # ── HTML 크롤링 ───────────────────────────────────────────────
    def _crawl(self, html: str, page_url: str = "") -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # 다양한 선택자 시도
            containers = (
                soup.select("ul.goods_list > li")
                or soup.select("div.goods_wrap ul li")
                or soup.select(".goods_list_wrap li.item")
                or soup.select("li.goods_item")
                or soup.select("div[class*='item_list'] li")
                or soup.select("ul[class*='list'] > li")
            )

            # 선택자 없으면 상품 링크 기반으로 전체 스캔
            if not containers:
                containers = self._find_product_containers(soup)

            total_li = len(soup.select("li"))
            print(f"[온채널 크롤링] 전체 li={total_li}, 매칭={len(containers)}")

            for item in containers:
                try:
                    result = self._extract_item(item)
                    if result:
                        results.append(result)
                except Exception:
                    continue

        except Exception as e:
            print(f"[온채널 파싱 오류] {e}")
        return results

    def _find_product_containers(self, soup: BeautifulSoup) -> list:
        """상품 링크 패턴으로 컨테이너 찾기"""
        product_links = soup.find_all("a", href=re.compile(r"(goods_view|item_view|vnum=|num=)\d+"))
        containers = []
        for link in product_links:
            parent = link.find_parent("li") or link.find_parent("div")
            if parent and parent not in containers:
                containers.append(parent)
        return containers

    def _extract_item(self, item) -> dict | None:
        """개별 상품 컨테이너에서 정보 추출"""
        # 상품명
        name_el = (item.select_one(".goods_name,.item_name,.name,strong.title")
                   or item.select_one("a.goods_link > span")
                   or item.select_one("a[class*='name']")
                   or item.select_one("strong")
                   or item.select_one("a"))
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if len(name) < 2 or name.isdigit():
            return None

        # 가격
        price_el = item.select_one(".goods_price,.price,[class*='price']")
        price = 0
        if price_el:
            nums = re.sub(r"[^0-9]", "", price_el.get_text())
            price = int(nums) if nums else 0

        # 배송비
        deli_el = item.select_one(".delivery,[class*='deli'],[class*='ship']")
        delivery = 3000
        if deli_el:
            dt = deli_el.get_text(strip=True)
            if "무료" in dt:
                delivery = 0
            else:
                dn = re.sub(r"[^0-9]", "", dt)
                delivery = int(dn) if dn else 3000

        # 업체 등급/평점
        grade_el = item.select_one("[class*='grade'],[class*='rating'],[class*='level'],.score")
        seller_grade = grade_el.get_text(strip=True) if grade_el else "- 온채널"

        # 이미지
        img_el = item.select_one("img[src]")
        image_url = ""
        if img_el:
            src = img_el.get("src","") or img_el.get("data-src","")
            if src and not src.endswith("loading.gif"):
                image_url = src if src.startswith("http") else f"https://www.onch3.co.kr{src}"

        # 상품 ID (링크에서 추출)
        link_el = item.select_one("a[href]")
        href = link_el["href"] if link_el else ""
        pid_m = re.search(r"num=(\d+)|vnum=(\d+)|no=(\d+)|goods_no=(\d+)", href)
        pid = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
        if not pid:
            return None

        return {
            "site": "온채널", "product_id": f"OC_{pid}",
            "name": name, "supply_price": price,
            "delivery_fee": delivery, "status": "Y",
            "seller_grade": seller_grade,
            "image_url": image_url,
        }
