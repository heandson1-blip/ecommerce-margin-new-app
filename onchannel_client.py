"""
onchannel_client.py
온채널 상품 검색: 로그인 세션 + HTML 크롤링
실제 검색 URL: onch_main.html?search_txt=키워드
"""
import requests, re, time
from bs4 import BeautifulSoup


class OnchannelClient:
    BASE = "https://www.onch3.co.kr"
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Connection": "keep-alive",
    }

    def __init__(self, user_id="", password=""):
        self.user_id  = user_id
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._logged_in = False

    def login(self) -> bool:
        if not self.user_id or not self.password:
            return False
        try:
            self.session.get(f"{self.BASE}/", timeout=10)
            time.sleep(0.3)
            self.session.post(
                f"{self.BASE}/member_action.php",
                data={"mode":"login","id":self.user_id,
                      "passwd":self.password,"save_id":"Y"},
                timeout=15, allow_redirects=True
            )
            check = self.session.get(f"{self.BASE}/mypage_main.php", timeout=10)
            if "로그아웃" in check.text or self.user_id in check.text:
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
        if not self._logged_in:
            self.login()  # 실패해도 비로그인으로 시도

        all_results = []

        # 온채널 실제 검색 URL 패턴들
        search_configs = [
            # (URL패턴, params)
            (f"{self.BASE}/onch_main.html", {"search_txt": keyword}),
            (f"{self.BASE}/goods_search.php", {"skw": keyword, "sm": "goods_name"}),
            (f"{self.BASE}/data_center.php",  {"skw": keyword}),
        ]

        for base_url, base_params in search_configs:
            for pg in range(1, max_pages + 1):
                try:
                    params = {**base_params, "page": pg}
                    resp = self.session.get(base_url, params=params, timeout=15)
                    if resp.status_code != 200:
                        continue
                    resp.encoding = "utf-8"
                    items = self._crawl(resp.text)
                    if not items:
                        print(f"[온채널] {base_url.split('/')[-1]}: 결과 없음")
                        break
                    all_results.extend(items)
                    print(f"[온채널] {base_url.split('/')[-1]} pg={pg} → {len(items)}개")
                    if len(items) < 5 or len(all_results) >= page_size:
                        break
                    time.sleep(0.5)
                except Exception as e:
                    print(f"[온채널] {base_url}: {e}")
                    break
            if all_results:
                break

        if not all_results:
            print("[온채널] 검색 결과 없음 — SPA/JS 렌더링으로 파싱 불가")
        return all_results[:page_size]

    def _crawl(self, html: str) -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # 상품 컨테이너 셀렉터 (온채널 HTML 구조 다수 시도)
            containers = (
                soup.select("ul.goods_list > li")
                or soup.select("div.goods_list_wrap li")
                or soup.select("li.item_box")
                or soup.select(".prd_list li")
                or soup.select(".goods_wrap li")
                or soup.select("li.goods_item")
                or soup.select("div[class*='item'] li")
                or self._find_by_link_pattern(soup)
            )

            all_li = soup.select("li")
            print(f"[온채널 파싱] 전체 li={len(all_li)}, 매칭={len(containers)}")

            for item in containers:
                try:
                    result = self._extract(item)
                    if result:
                        results.append(result)
                except Exception:
                    continue
        except Exception as e:
            print(f"[온채널 파싱 오류] {e}")
        return results

    def _find_by_link_pattern(self, soup: BeautifulSoup) -> list:
        """상품 상세 링크 패턴으로 컨테이너 역탐색"""
        links = soup.find_all("a", href=re.compile(
            r"(goods_view|item_view|onch_pb2b|vnum=|num=|goods_no=)\d*", re.I))
        seen, containers = set(), []
        for link in links:
            parent = link.find_parent("li") or link.find_parent("div")
            if parent:
                pid = id(parent)
                if pid not in seen:
                    seen.add(pid)
                    containers.append(parent)
        return containers

    def _extract(self, item) -> dict | None:
        # 상품명
        name_el = (item.select_one(".goods_name,.item_name,.prd_name,.name,strong.tit")
                   or item.select_one("a[class*='name'],a[class*='goods'],a[class*='link'] span")
                   or item.select_one("strong") or item.select_one("a"))
        if not name_el:
            return None
        name = name_el.get_text(strip=True)
        if len(name) < 2 or name.isdigit():
            return None

        # 가격
        price_el = item.select_one(".goods_price,.price,.prd_price,[class*='price']")
        price = 0
        if price_el:
            nums = re.sub(r"[^0-9]", "", price_el.get_text())
            price = int(nums) if nums else 0

        # 배송비
        deli_el = item.select_one(".delivery,[class*='deli'],[class*='ship'],[class*='fee']")
        delivery = 3000
        if deli_el:
            dt = deli_el.get_text(strip=True)
            delivery = 0 if "무료" in dt else int(re.sub(r"[^0-9]", "", dt) or 3000)

        # 이미지
        img_el = (item.select_one("img.goods_img,img.thumb,img[class*='img'],img[class*='thumb']")
                  or item.select_one("img"))
        image_url = ""
        if img_el:
            src = img_el.get("src","") or img_el.get("data-src","") or img_el.get("data-lazy","")
            if src and "loading" not in src and len(src) > 5:
                image_url = src if src.startswith("http") else f"{self.BASE}{src}"

        # 업체 등급
        grade_el = item.select_one("[class*='grade'],[class*='star'],[class*='rating'],[class*='level']")
        seller_grade = grade_el.get_text(strip=True) if grade_el else "- 온채널"

        # 상품 ID
        link_el = item.select_one("a[href]")
        href = link_el["href"] if link_el else ""
        pid_m = re.search(r"num=(\d+)|vnum=(\d+)|no=(\d+)|goods_no=(\d+)", href)
        pid = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
        if not pid:
            return None

        return {
            "site":"온채널","product_id":f"OC_{pid}","name":name,
            "supply_price":price,"delivery_fee":delivery,"status":"Y",
            "seller_grade":seller_grade,"image_url":image_url,
        }
