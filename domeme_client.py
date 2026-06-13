"""
domeme_client.py — 도매매/도매꾹 API 클라이언트
- 페이지네이션(pg 파라미터)으로 최대 500개 수집
- 관심 등록 시 getItemView로 정확한 배송비 조회
"""

import requests
import json
import time


class DomeameClient:
    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.base_url = "https://domeggook.com/ssl/api/"

    def fetch_product_list(
        self,
        market: str = "supply",
        keyword: str = "",
        category_code: str = "0000",
        page_size: int = 50,
        max_pages: int = 2,
    ) -> list[dict]:
        """
        상품 목록 조회 (페이지네이션).
        ※ 목록 API에는 배송비 필드가 없어 3,000원 기본값 사용.
          정확한 배송비는 fetch_item_detail()로 확인 가능.
        """
        site_name = "도매매" if market == "supply" else "도매꾹"
        page_size = max(10, min(page_size, 100))
        max_pages = max(1,  min(max_pages, 10))

        all_results = []
        for pg in range(1, max_pages + 1):
            params = {
                "ver": "4.1", "mode": "getItemList",
                "aid": self.api_key, "market": market,
                "om": "json", "sz": page_size, "pg": pg,
            }
            if category_code and category_code != "0000":
                params["ca"] = category_code
            if keyword:
                params["kw"] = keyword

            try:
                resp = requests.get(self.base_url, params=params, timeout=20)
                if resp.status_code != 200:
                    print(f"[{site_name}] HTTP {resp.status_code} (pg={pg})")
                    break
                page_data = self._parse_list(resp.text, site_name)
                if not page_data:
                    break
                all_results.extend(page_data)
                print(f"[{site_name}] pg={pg} → {len(page_data)}개 (누적 {len(all_results)}개)")
                if len(page_data) < page_size:
                    break
                if pg < max_pages:
                    time.sleep(0.3)
            except requests.exceptions.Timeout:
                print(f"[{site_name}] 타임아웃 (pg={pg})")
                break
            except Exception as e:
                print(f"[{site_name}] 오류: {e}")
                break

        return all_results

    def fetch_item_detail(self, product_id: str) -> dict | None:
        """
        단일 상품 상세 조회 (getItemView).
        배송비·상태·가격 모두 정확한 값 반환.
        배치 및 관심 등록 시 사용.
        """
        params = {
            "ver": "4.1", "mode": "getItemView",
            "aid": self.api_key, "no": product_id, "om": "json",
        }
        try:
            resp = requests.get(self.base_url, params=params, timeout=15)
            if resp.status_code != 200:
                return None
            data = json.loads(resp.text)
            item = data.get("domeggook", {}).get("item", {})
            if not item:
                return None

            s = self._safe
            state  = s(item.get("state"), "2")
            stock  = s(item.get("stock"), "999")
            status = "N" if state in ["3", "4"] or stock == "0" else "Y"

            raw_price    = s(item.get("price", "0")).replace(",", "")
            raw_delivery = s(item.get("delivery", "0")).replace(",", "")
            delivery_fee = int(raw_delivery) if raw_delivery.isdigit() and int(raw_delivery) >= 0 else 3000

            return {
                "status":       status,
                "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                "delivery_fee": delivery_fee,
            }
        except Exception as e:
            print(f"[상품 상세 오류] {product_id}: {e}")
            return None

    # ── 내부 헬퍼 ────────────────────────────────
    @staticmethod
    def _safe(value, default="") -> str:
        if isinstance(value, dict):
            return value.get("#cdata-section", value.get("#text", default))
        return str(value) if value is not None else default

    def _parse_list(self, raw: str, site_name: str) -> list[dict]:
        results = []
        try:
            data = json.loads(raw)
            err  = data.get("domeggook", {}).get("error")
            if err:
                msg = err if isinstance(err, str) else err.get("message", "알 수 없는 오류")
                print(f"[API Error] {site_name}: {msg}")
                return []
            items = data.get("domeggook", {}).get("list", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                return []

            s = self._safe
            for item in items:
                state  = s(item.get("state"), "2")
                stock  = s(item.get("stock"), "999")
                status = "N" if state in ["3", "4"] or stock == "0" else "Y"
                raw_price = s(item.get("price", "0")).replace(",", "")
                # ※ 목록 API는 배송비 필드 미제공 → 3,000원 기본값
                #   관심 등록 시 fetch_item_detail()로 정확한 값 갱신됨
                results.append({
                    "site":         site_name,
                    "product_id":   s(item.get("no"), ""),
                    "name":         s(item.get("title"), "이름 없음"),
                    "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                    "delivery_fee": 3000,   # 목록 API 한계 — 상세 조회 시 갱신
                    "status":       status,
                })
        except json.JSONDecodeError as e:
            print(f"[파싱 오류] {e}")
        except Exception as e:
            print(f"[파싱 오류] {e}")
        return results
