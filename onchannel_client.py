"""
onchannel_client.py — 온채널 상품 검색 클라이언트
온채널은 외부 공개 API가 없으므로 웹 검색 결과를 파싱합니다.
(robots.txt 및 이용약관 범위 내 공개 검색 페이지 활용)
"""

import requests
from bs4 import BeautifulSoup
import re
import time


class OnchannelClient:
    """온채널 상품 검색 (웹 파싱 방식)"""

    BASE_URL  = "https://www.onch3.co.kr"
    SEARCH_URL = "https://www.onch3.co.kr/goods_search.php"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    def fetch_product_list(
        self,
        keyword: str = "",
        category_code: str = "",
        page_size: int = 50,
        max_pages: int = 1,
    ) -> list[dict]:
        """온채널 상품 검색. keyword 또는 category_code 필요."""
        if not keyword and not category_code:
            return []

        all_results = []
        for pg in range(1, max_pages + 1):
            try:
                params = {"skw": keyword, "page": pg}
                if category_code:
                    params["ca1"] = category_code

                resp = requests.get(
                    self.SEARCH_URL, params=params,
                    headers=self.HEADERS, timeout=15
                )
                if resp.status_code != 200:
                    print(f"[온채널] HTTP {resp.status_code} (pg={pg})")
                    break

                resp.encoding = "utf-8"
                items = self._parse(resp.text)
                if not items:
                    break

                all_results.extend(items)
                print(f"[온채널] pg={pg} → {len(items)}개 (누적 {len(all_results)}개)")

                if len(items) < 20:   # 마지막 페이지 추정
                    break
                if pg < max_pages:
                    time.sleep(0.5)

                if len(all_results) >= page_size:
                    break

            except requests.exceptions.Timeout:
                print(f"[온채널] 타임아웃 (pg={pg})")
                break
            except Exception as e:
                print(f"[온채널] 오류: {e}")
                break

        return all_results[:page_size]

    def _parse(self, html: str) -> list[dict]:
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")

            # 온채널 상품 카드 파싱 (구조 변경 시 수정 필요)
            items = soup.select(".goods_list_item, .item_wrap, li.goods_item")
            if not items:
                # 대안 셀렉터 시도
                items = soup.select("li[class*='goods'], div[class*='goods_item']")

            for item in items:
                try:
                    # 상품명
                    name_el = item.select_one(
                        ".goods_name, .item_name, a[class*='name'], .name"
                    )
                    name = name_el.get_text(strip=True) if name_el else ""
                    if not name:
                        continue

                    # 가격
                    price_el = item.select_one(
                        ".goods_price, .price, span[class*='price']"
                    )
                    price_txt = price_el.get_text(strip=True) if price_el else "0"
                    price = int(re.sub(r"[^0-9]", "", price_txt) or 0)

                    # 상품 ID / 링크
                    link_el = item.select_one("a[href]")
                    href    = link_el["href"] if link_el else ""
                    pid_match = re.search(r"num=(\d+)|no=(\d+)|goods_no=(\d+)", href)
                    pid = next((g for g in (pid_match.groups() if pid_match else []) if g), "")

                    if not pid:
                        continue

                    results.append({
                        "site":         "온채널",
                        "product_id":   f"OC_{pid}",
                        "name":         name,
                        "supply_price": price,
                        "delivery_fee": 3000,
                        "status":       "Y",
                    })
                except Exception:
                    continue

        except Exception as e:
            print(f"[온채널 파싱 오류] {e}")

        return results
