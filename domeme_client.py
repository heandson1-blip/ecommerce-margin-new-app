import requests, json, time

class DomeameClient:
    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.base_url = "https://domeggook.com/ssl/api/"

    def fetch_product_list(self, market="supply", keyword="", category_code="0000",
                           page_size=50, max_pages=2) -> list[dict]:
        site_name = "도매매" if market == "supply" else "도매꾹"
        page_size = max(10, min(page_size, 100))
        max_pages = max(1, min(max_pages, 10))
        all_results = []
        for pg in range(1, max_pages + 1):
            params = {"ver":"4.1","mode":"getItemList","aid":self.api_key,
                      "market":market,"om":"json","sz":page_size,"pg":pg}
            if category_code and category_code != "0000":
                params["ca"] = category_code
            if keyword:
                params["kw"] = keyword
            try:
                resp = requests.get(self.base_url, params=params, timeout=20)
                if resp.status_code != 200:
                    break
                page_data = self._parse_list(resp.text, site_name)
                if not page_data:
                    break
                all_results.extend(page_data)
                print(f"[{site_name}] pg={pg} → {len(page_data)}개")
                if len(page_data) < page_size:
                    break
                if pg < max_pages:
                    time.sleep(0.3)
            except Exception as e:
                print(f"[{site_name}] 오류: {e}"); break
        return all_results

    def fetch_item_detail(self, product_id: str) -> dict | None:
        """상세 조회 — 등급 포함 모든 필드 파싱"""
        params = {"ver":"4.1","mode":"getItemView","aid":self.api_key,
                  "no":product_id,"om":"json"}
        try:
            resp = requests.get(self.base_url, params=params, timeout=15)
            if resp.status_code != 200:
                return None
            data = json.loads(resp.text)
            item = data.get("domeggook", {}).get("item", {})
            if not item:
                return None

            # ★ 디버그: seller 객체 전체 출력 (등급 필드명 확인용)
            seller_raw = item.get("seller", {})
            print(f"[DEBUG seller fields] {seller_raw}")

            s = self._safe
            state  = s(item.get("state"), "2")
            stock  = s(item.get("stock"), "999")
            status = "N" if state in ["3","4"] or stock=="0" else "Y"
            raw_price    = s(item.get("price","0")).replace(",","")
            delivery_fee = self._parse_delivery(item.get("deli", {}))
            seller_grade = self._parse_grade(seller_raw)

            return {
                "status":       status,
                "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                "delivery_fee": delivery_fee,
                "seller_grade": seller_grade,
            }
        except Exception as e:
            print(f"[상세 오류] {product_id}: {e}")
            return None

    @staticmethod
    def _parse_grade(seller) -> str:
        """
        도매꾹 seller 객체에서 등급 파싱.
        실제 필드명: grade / level / point / star 등 API 버전마다 다를 수 있음.
        디버그 로그로 실제 필드명 확인 후 정확한 필드 사용.
        """
        if not seller:
            return "- 미확인"

        def safe(v):
            if isinstance(v, dict):
                return v.get("#cdata-section", v.get("#text", ""))
            return str(v).strip() if v is not None else ""

        # 가능한 등급 필드명 모두 시도
        grade_val = (
            safe(seller.get("grade"))
            or safe(seller.get("level"))
            or safe(seller.get("sellerGrade"))
            or safe(seller.get("seller_grade"))
            or safe(seller.get("rating"))
            or safe(seller.get("rank"))
            or safe(seller.get("point"))
            or ""
        )

        if not grade_val:
            return "- 미확인"

        # 등급 매핑 (대소문자 무관)
        grade_map = {
            "s": "⭐ S등급", "a": "🔵 A등급", "b": "🟢 B등급",
            "c": "🟡 C등급", "d": "🟠 D등급", "e": "🔴 E등급",
            "1": "⭐ 1등급", "2": "🔵 2등급", "3": "🟢 3등급",
            "4": "🟡 4등급", "5": "🟠 5등급",
        }
        key = grade_val.lower().strip()
        return grade_map.get(key, f"- {grade_val}")

    @staticmethod
    def _parse_delivery(deli) -> int:
        if not deli:
            return 3000
        if isinstance(deli, (str, int)):
            raw = str(deli).replace(",","")
            return int(raw) if raw.isdigit() else 3000
        def safe(v, d=""):
            if isinstance(v, dict):
                return v.get("#cdata-section", v.get("#text", d))
            return str(v) if v is not None else d
        who = safe(deli.get("who","")).upper()
        if who == "F":
            return 0
        fee_raw = safe(deli.get("fee","0")).replace(",","")
        return int(fee_raw) if fee_raw.isdigit() else 3000

    @staticmethod
    def _safe(value, default="") -> str:
        if isinstance(value, dict):
            return value.get("#cdata-section", value.get("#text", default))
        return str(value) if value is not None else default

    def _parse_list(self, raw: str, site_name: str) -> list[dict]:
        results = []
        try:
            data  = json.loads(raw)
            err   = data.get("domeggook",{}).get("error")
            if err:
                print(f"[API Error] {site_name}: {err}")
                return []
            items = data.get("domeggook",{}).get("list",{}).get("item",[])
            if isinstance(items, dict): items = [items]
            if not isinstance(items, list): return []

            # ★ 첫 번째 아이템의 seller 필드 디버그
            if items:
                print(f"[DEBUG list seller] {items[0].get('seller', 'NO_SELLER_FIELD')}")

            s = self._safe
            for item in items:
                state  = s(item.get("state"),"2")
                stock  = s(item.get("stock"),"999")
                status = "N" if state in ["3","4"] or stock=="0" else "Y"
                raw_price    = s(item.get("price","0")).replace(",","")
                delivery_fee = self._parse_delivery(item.get("deli", {}))
                seller_grade = self._parse_grade(item.get("seller", {}))
                results.append({
                    "site":         site_name,
                    "product_id":   s(item.get("no"),""),
                    "name":         s(item.get("title"),"이름 없음"),
                    "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                    "delivery_fee": delivery_fee,
                    "status":       status,
                    "seller_grade": seller_grade,
                })
        except Exception as e:
            print(f"[파싱 오류] {e}")
        return results
