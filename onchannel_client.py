"""
onchannel_client.py v11
온채널(onch3.co.kr)은 Streamlit Cloud 서버 IP를 403으로 완전 차단합니다.
로컬 PC에서 실행 시에는 로그인 후 크롤링이 가능할 수 있습니다.
클라우드 환경에서는 온채널 상품 검색이 불가합니다.
"""
import requests, re, time
from bs4 import BeautifulSoup


class OnchannelClient:
    BASE = "https://www.onch3.co.kr"
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    BLOCKED_MSG = ("온채널은 클라우드 서버 IP를 차단하고 있어 검색이 불가합니다.\n"
                   "온채널 상품은 직접 사이트(onch3.co.kr)에서 확인해 주세요.")

    def __init__(self, user_id="", password=""):
        self.user_id  = user_id
        self.password = password
        self.session  = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._logged_in = False
        self._blocked   = False

    def login(self) -> bool:
        if not self.user_id or not self.password:
            print("[온채널] ID/PW 미설정")
            return False
        try:
            r = self.session.get(f"{self.BASE}/", timeout=10)
            if r.status_code == 403:
                self._blocked = True
                print("[온채널] 서버 IP 차단 (403)")
                return False
            time.sleep(0.3)
            r2 = self.session.post(
                f"{self.BASE}/member_action.php",
                data={"mode":"login","id":self.user_id,"passwd":self.password,"save_id":"Y"},
                timeout=15, allow_redirects=True
            )
            if r2.status_code == 403:
                self._blocked = True
                return False
            check = self.session.get(f"{self.BASE}/mypage_main.php", timeout=10)
            if "로그아웃" in check.text or self.user_id in check.text:
                self._logged_in = True
                print("[온채널] 로그인 성공")
                return True
            print("[온채널] 로그인 실패")
            return False
        except Exception as e:
            print(f"[온채널] 오류: {e}")
            return False

    def fetch_product_list(self, keyword="", page_size=50, max_pages=2) -> list[dict]:
        if not keyword:
            return []
        if self._blocked:
            raise Exception(self.BLOCKED_MSG)
        if not self._logged_in:
            ok = self.login()
            if not ok:
                if self._blocked:
                    raise Exception(self.BLOCKED_MSG)
                raise Exception("온채널 로그인 실패 — ID/PW를 확인하세요.")

        all_results = []
        endpoints = [
            (f"{self.BASE}/onch_main.html",  {"search_txt": keyword}),
            (f"{self.BASE}/goods_search.php", {"skw": keyword, "sm": "goods_name"}),
        ]
        for url, base_params in endpoints:
            for pg in range(1, max_pages + 1):
                try:
                    params = {**base_params, "page": pg}
                    resp = self.session.get(url, params=params, timeout=15)
                    if resp.status_code == 403:
                        self._blocked = True
                        raise Exception(self.BLOCKED_MSG)
                    if resp.status_code != 200:
                        break
                    resp.encoding = "utf-8"
                    items = self._crawl(resp.text)
                    if not items: break
                    all_results.extend(items)
                    print(f"[온채널] {url.split('/')[-1]} pg={pg} → {len(items)}개")
                    if len(items) < 5 or len(all_results) >= page_size: break
                    time.sleep(0.5)
                except Exception as e:
                    raise
            if all_results: break
        return all_results[:page_size]

    def _crawl(self, html: str) -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            containers = (
                soup.select("ul.goods_list > li")
                or soup.select("li.item_box")
                or soup.select("li.goods_item")
                or soup.select("div.goods_list_wrap li")
                or self._find_by_links(soup)
            )
            for item in containers:
                r = self._extract(item)
                if r: results.append(r)
        except Exception as e:
            print(f"[온채널 파싱] {e}")
        return results

    def _find_by_links(self, soup):
        links = soup.find_all("a", href=re.compile(r"(goods|item|vnum=|num=)\d*", re.I))
        seen, out = set(), []
        for link in links:
            p = link.find_parent("li") or link.find_parent("div")
            if p and id(p) not in seen:
                seen.add(id(p)); out.append(p)
        return out

    def _extract(self, item) -> dict | None:
        name_el = (item.select_one(".goods_name,.item_name,.name,strong.tit")
                   or item.select_one("strong") or item.select_one("a"))
        if not name_el: return None
        name = name_el.get_text(strip=True)
        if len(name) < 2 or name.isdigit(): return None

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

        img_el = item.select_one("img[src],img[data-src]")
        image_url = ""
        if img_el:
            src = img_el.get("src","") or img_el.get("data-src","")
            if src and "loading" not in src:
                image_url = src if src.startswith("http") else f"{self.BASE}{src}"

        link_el = item.select_one("a[href]")
        href = link_el["href"] if link_el else ""
        pid_m = re.search(r"num=(\d+)|vnum=(\d+)|no=(\d+)", href)
        pid = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
        if not pid: return None

        return {"site":"온채널","product_id":f"OC_{pid}","name":name,
                "supply_price":price,"delivery_fee":delivery,"status":"Y",
                "seller_grade":"","image_url":image_url}
