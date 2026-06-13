"""
onchannel_client.py
온채널 로그인 후 상품 목록 파싱.
Secrets: ONCHANNEL_ID / ONCHANNEL_PW
"""
import requests, re, time
from bs4 import BeautifulSoup


class OnchannelClient:
    BASE    = "https://www.onch3.co.kr"
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

    # ── 로그인 ──────────────────────────────────
    def login(self) -> bool:
        if not self.user_id or not self.password:
            print("[온채널] ID/PW 미설정")
            return False
        try:
            # 1) 로그인 페이지 GET (쿠키/토큰 확보)
            self.session.get(f"{self.BASE}/member_form.php", timeout=10)
            # 2) POST 로그인
            payload = {"mode":"login","id":self.user_id,"passwd":self.password,
                       "save_id":"Y","url":"/"}
            resp = self.session.post(f"{self.BASE}/member_action.php",
                                     data=payload, timeout=15, allow_redirects=True)
            # 로그인 성공 판별: 응답에 로그아웃 링크 존재 여부
            if "로그아웃" in resp.text or "logout" in resp.text.lower():
                self._logged_in = True
                print("[온채널] 로그인 성공")
                return True
            # 쿠키 기반 재확인
            home = self.session.get(self.BASE, timeout=10)
            if "로그아웃" in home.text:
                self._logged_in = True
                print("[온채널] 로그인 성공 (재확인)")
                return True
            print("[온채널] 로그인 실패 — ID/PW 확인")
            return False
        except Exception as e:
            print(f"[온채널] 로그인 오류: {e}")
            return False

    # ── 상품 검색 ───────────────────────────────
    def fetch_product_list(self, keyword="", page_size=50, max_pages=2) -> list[dict]:
        if not keyword:
            return []
        if not self._logged_in and not self.login():
            return []

        all_results = []
        for pg in range(1, max_pages + 1):
            try:
                # 온채널 검색 URL (로그인 세션 사용)
                params = {"skw": keyword, "page": pg}
                resp   = self.session.get(
                    f"{self.BASE}/goods_search.php",
                    params=params, timeout=15
                )
                if resp.status_code != 200:
                    break
                resp.encoding = "utf-8"
                items = self._parse(resp.text)
                if not items:
                    break
                all_results.extend(items)
                print(f"[온채널] pg={pg} → {len(items)}개")
                if len(items) < 10 or len(all_results) >= page_size:
                    break
                if pg < max_pages:
                    time.sleep(0.5)
            except Exception as e:
                print(f"[온채널] 검색 오류: {e}"); break

        return all_results[:page_size]

    # ── HTML 파싱 ────────────────────────────────
    def _parse(self, html: str) -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # 온채널 상품 카드 셀렉터 (2024 기준 구조)
            items = (
                soup.select("ul.goods_list > li.item")
                or soup.select("div.goods_list li")
                or soup.select("li.goods_item")
                or soup.select(".goods_wrap li")
                or soup.select("li[class*='item']")
            )

            for item in items:
                try:
                    # 상품명
                    name_el = (item.select_one(".goods_name, .item_name, .name, strong") or
                               item.select_one("a"))
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    if len(name) < 2:
                        continue

                    # 공급가
                    price_el = item.select_one(".goods_price, .price, [class*='price']")
                    price_txt = price_el.get_text(strip=True) if price_el else "0"
                    price     = int(re.sub(r"[^0-9]", "", price_txt) or 0)

                    # 배송비
                    deli_el = item.select_one(".delivery, [class*='deli'], [class*='ship']")
                    if deli_el:
                        d_txt = deli_el.get_text(strip=True)
                        if "무료" in d_txt:
                            delivery = 0
                        else:
                            d_num = re.sub(r"[^0-9]", "", d_txt)
                            delivery = int(d_num) if d_num else 3000
                    else:
                        delivery = 3000

                    # 상품 ID
                    link_el = item.select_one("a[href]")
                    href    = link_el["href"] if link_el else ""
                    pid_m   = re.search(r"num=(\d+)|vnum=(\d+)|no=(\d+)", href)
                    pid     = next((g for g in (pid_m.groups() if pid_m else []) if g), "")
                    if not pid:
                        continue

                    results.append({
                        "site": "온채널", "product_id": f"OC_{pid}",
                        "name": name, "supply_price": price,
                        "delivery_fee": delivery, "status": "Y",
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"[온채널 파싱] {e}")
        return results
