import requests
import json


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
    ) -> list[dict]:
        """
        도매매/도매꾹 상품 목록 조회.
        page_size: API 파라미터 sz (최대 200, 실제 반환 수는 API 서버 정책에 따름)
        """
        site_name = "도매매" if market == "supply" else "도매꾹"
        page_size = max(10, min(page_size, 200))  # 10~200 범위 강제

        params = {
            "ver": "4.1",
            "mode": "getItemList",
            "aid": self.api_key,
            "market": market,
            "om": "json",
            "sz": page_size,
        }
        if category_code and category_code != "0000":
            params["ca"] = category_code
        if keyword:
            params["kw"] = keyword

        try:
            resp = requests.get(self.base_url, params=params, timeout=20)
            if resp.status_code == 200:
                result = self._parse(resp.text, site_name)
                print(f"[{site_name}] {len(result)}개 파싱 완료 (요청 sz={page_size})")
                return result
            else:
                print(f"[{site_name}] HTTP {resp.status_code} 오류")
                return []
        except requests.exceptions.Timeout:
            print(f"[{site_name}] 요청 시간 초과 (20초)")
            return []
        except requests.exceptions.RequestException as e:
            print(f"[{site_name}] 통신 오류: {e}")
            return []

    def fetch_item_detail(self, product_id: str) -> dict | None:
        """단일 상품 최신 정보 조회 (getItemView) — 배치용"""
        params = {
            "ver": "4.1",
            "mode": "getItemView",
            "aid": self.api_key,
            "no": product_id,
            "om": "json",
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
            state = s(item.get("state"), "2")
            stock = s(item.get("stock"), "999")
            status = "N" if state in ["3", "4"] or stock == "0" else "Y"
            raw = s(item.get("price", "0")).replace(",", "")
            return {
                "status":       status,
                "supply_price": int(raw) if raw.isdigit() else 0,
            }
        except Exception as e:
            print(f"[상품 조회 오류] {product_id}: {e}")
            return None

    # ── 내부 헬퍼 ──────────────────────────────
    @staticmethod
    def _safe(value, default="") -> str:
        if isinstance(value, dict):
            return value.get("#cdata-section", value.get("#text", default))
        return str(value) if value is not None else default

    def _parse(self, raw: str, site_name: str) -> list[dict]:
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
                state = s(item.get("state"), "2")
                stock = s(item.get("stock"), "999")
                status = "N" if state in ["3", "4"] or stock == "0" else "Y"

                raw_price = s(item.get("price", "0")).replace(",", "")
                # 배송비: API에 필드가 있으면 사용, 없으면 3000원 기본값
                raw_delivery = s(item.get("delivery", "0")).replace(",", "")
                delivery_fee = int(raw_delivery) if raw_delivery.isdigit() and int(raw_delivery) > 0 else 3000

                results.append({
                    "site":         site_name,
                    "product_id":   s(item.get("no"), ""),
                    "name":         s(item.get("title"), "이름 없음"),
                    "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                    "delivery_fee": delivery_fee,
                    "status":       status,
                })
        except json.JSONDecodeError as e:
            print(f"[파싱 오류] JSON 디코딩 실패: {e}")
        except Exception as e:
            print(f"[파싱 오류] {e}")
        return results
