import requests, json, time

GRADE_MAP = {
    "s":"⭐S", "platinum":"⭐S",
    "a":"🔵A", "gold":"🔵A",
    "b":"🟢B", "silver":"🟢B",
    "c":"🟡C", "bronze":"🟡C",
    "d":"🟠D", "e":"🔴E", "f":"🔴F",
    "1":"⭐1","2":"🔵2","3":"🟢3","4":"🟡4","5":"🟠5",
}


class DomeameClient:
    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.base_url = "https://domeggook.com/ssl/api/"

    # ── 상품 목록 조회 ────────────────────────────────────────
    def fetch_product_list(self, market="supply", keyword="",
                           category_code="0000", page_size=50, max_pages=2) -> list[dict]:
        site_name = "도매매" if market == "supply" else "도매꾹"
        page_size = max(10, min(page_size, 100))
        max_pages = max(1, min(max_pages, 10))
        all_results = []
        first = True
        for pg in range(1, max_pages + 1):
            params = {"ver":"4.1","mode":"getItemList","aid":self.api_key,
                      "market":market,"om":"json","sz":page_size,"pg":pg}
            if category_code and category_code != "0000":
                params["ca"] = category_code
            if keyword:
                params["kw"] = keyword
            try:
                resp = requests.get(self.base_url, params=params, timeout=20)
                if resp.status_code != 200: break
                items, keys = self._parse_list(resp.text, site_name, dump=first)
                first = False
                if not items: break
                all_results.extend(items)
                print(f"[{site_name}] pg={pg} → {len(items)}개")
                if len(items) < page_size: break
                if pg < max_pages: time.sleep(0.3)
            except Exception as e:
                print(f"[{site_name}] 오류: {e}"); break
        return all_results

    # ── 단일 상품 상세 조회 (등급+배송비+이미지) ──────────────
    def fetch_item_detail(self, product_id: str) -> dict | None:
        params = {"ver":"4.1","mode":"getItemView","aid":self.api_key,
                  "no":product_id,"om":"json"}
        try:
            resp = requests.get(self.base_url, params=params, timeout=15)
            if resp.status_code != 200: return None
            data = json.loads(resp.text)
            item = data.get("domeggook", {}).get("item", {})
            if not item: return None

            s = self._safe
            state = s(item.get("state","2"))
            stock = s(item.get("stock","999"))
            status = "N" if state in ["3","4"] or stock=="0" else "Y"
            raw_price = s(item.get("price","0")).replace(",","")
            delivery  = self._parse_deli(item.get("deli", {}))
            grade     = self._parse_grade(item.get("seller", {}))
            image_url = self._parse_image(item, product_id)

            # 디버그: 실제 필드명 확인
            print(f"[상세 keys] {list(item.keys())}")
            print(f"[상세 seller] {item.get('seller','없음')}")

            return {
                "status":       status,
                "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                "delivery_fee": delivery,
                "seller_grade": grade,
                "image_url":    image_url,
            }
        except Exception as e:
            print(f"[상세 오류] {product_id}: {e}")
            return None

    # ── 배치 등급 조회 (첫 N개만 빠르게) ─────────────────────
    def batch_fetch_grades(self, products: list[dict], limit: int = 15) -> list[dict]:
        """
        상품 목록의 처음 limit개에 대해 상세 API를 순서대로 호출해
        seller_grade / delivery_fee / image_url 을 실제 값으로 갱신.
        나머지는 그대로 반환.
        """
        updated = []
        for i, prod in enumerate(products):
            if i < limit and prod.get("site") in ["도매매","도매꾹"]:
                detail = self.fetch_item_detail(str(prod["product_id"]))
                if detail:
                    prod = {**prod, **{k:v for k,v in detail.items() if v}}
                time.sleep(0.2)  # API 서버 부하 방지
            updated.append(prod)
        return updated

    # ── 헬퍼 ─────────────────────────────────────────────────
    @staticmethod
    def _safe(v, d="") -> str:
        if isinstance(v, dict):
            return v.get("#cdata-section", v.get("#text", d))
        return str(v).strip() if v is not None else d

    def _parse_grade(self, seller) -> str:
        if not seller: return ""
        s = self._safe
        raw = (s(seller.get("grade")) or s(seller.get("level"))
               or s(seller.get("sellerGrade")) or s(seller.get("rank"))
               or s(seller.get("rating")) or s(seller.get("star"))
               or s(seller.get("tier")) or s(seller.get("class")) or "")
        if not raw:
            if isinstance(seller, dict):
                print(f"[등급 필드 없음] seller keys: {list(seller.keys())}")
            return ""
        return GRADE_MAP.get(raw.lower().strip(), raw)

    def _parse_deli(self, deli) -> int:
        if not deli: return 3000
        if isinstance(deli, (str, int)):
            raw = str(deli).replace(",","")
            return int(raw) if raw.isdigit() else 3000
        s = self._safe
        who = s(deli.get("who","")).upper()
        if who == "F": return 0
        fee = s(deli.get("fee","0")).replace(",","")
        return int(fee) if fee.isdigit() else 3000

    def _parse_image(self, item: dict, pid: str) -> str:
        s = self._safe
        for field in ["img","image","thumb","thumbnail","photo","pic"]:
            val = s(item.get(field,""))
            if val and val.startswith("http"): return val
        return f"https://img.domeggook.com/main/{pid}/1.jpg" if pid else ""

    def _parse_list(self, raw: str, site_name: str, dump=False):
        results, keys = [], []
        try:
            data  = json.loads(raw)
            err   = data.get("domeggook",{}).get("error")
            if err:
                print(f"[API Error] {site_name}: {err}"); return [], []
            items = data.get("domeggook",{}).get("list",{}).get("item",[])
            if isinstance(items, dict): items = [items]
            if not isinstance(items, list): return [], []

            if dump and items:
                keys = list(items[0].keys())
                print(f"[목록 API 전체 키] {keys}")
                print(f"[목록 seller 값] {items[0].get('seller','없음')}")

            s = self._safe
            for item in items:
                state = s(item.get("state","2"))
                stock = s(item.get("stock","999"))
                status = "N" if state in ["3","4"] or stock=="0" else "Y"
                raw_price = s(item.get("price","0")).replace(",","")
                pid = s(item.get("no",""))
                # 목록 API — seller/deli/이미지 있으면 파싱, 없으면 빈값 (상세 조회로 갱신)
                grade     = self._parse_grade(item.get("seller",{}))
                delivery  = self._parse_deli(item.get("deli",{}))
                image_url = self._parse_image(item, pid)
                results.append({
                    "site":         site_name,
                    "product_id":   pid,
                    "name":         s(item.get("title","이름 없음")),
                    "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                    "delivery_fee": delivery,
                    "status":       status,
                    "seller_grade": grade,   # 목록엔 보통 없음 → 빈값
                    "image_url":    image_url,
                })
        except Exception as e:
            print(f"[파싱 오류] {e}")
        return results, keys
