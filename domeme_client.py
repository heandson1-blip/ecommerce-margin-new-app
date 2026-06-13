import requests, json, time

# 도매꾹 등급 매핑 (API 응답값 → 표시 문자)
GRADE_MAP = {
    "s":"⭐ S등급","platinum":"⭐ S등급",
    "a":"🔵 A등급","gold":"🔵 A등급",
    "b":"🟢 B등급","silver":"🟢 B등급",
    "c":"🟡 C등급","bronze":"🟡 C등급",
    "d":"🟠 D등급","d":"🟠 D등급",
    "e":"🔴 E등급","f":"🔴 F등급",
    "1":"⭐ 1등급","2":"🔵 2등급","3":"🟢 3등급",
    "4":"🟡 4등급","5":"🟠 5등급",
}


class DomeameClient:
    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.base_url = "https://domeggook.com/ssl/api/"

    # ── 목록 조회 ─────────────────────────────────────────────
    def fetch_product_list(self, market="supply", keyword="",
                           category_code="0000", page_size=50, max_pages=2) -> list[dict]:
        site_name = "도매매" if market == "supply" else "도매꾹"
        page_size = max(10, min(page_size, 100))
        max_pages = max(1,  min(max_pages, 10))
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
                print(f"[{site_name}] pg={pg} → {len(page_data)}개 (누적 {len(all_results)})")
                if len(page_data) < page_size:
                    break
                if pg < max_pages:
                    time.sleep(0.3)
            except Exception as e:
                print(f"[{site_name}] 오류: {e}"); break
        return all_results

    # ── 상세 조회 (관심 등록 시 배송비+등급 갱신) ──────────────
    def fetch_item_detail(self, product_id: str) -> dict | None:
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
            s = self._safe
            state  = s(item.get("state"), "2")
            stock  = s(item.get("stock"), "999")
            status = "N" if state in ["3","4"] or stock=="0" else "Y"
            raw_price    = s(item.get("price","0")).replace(",","")
            delivery_fee = self._parse_deli(item.get("deli", {}))
            # 상세 API seller 객체 — 실제 필드명 로깅
            seller_raw   = item.get("seller", {})
            seller_grade = self._parse_grade(seller_raw)
            print(f"[상세 seller raw] {json.dumps(seller_raw, ensure_ascii=False)}")
            return {
                "status":       status,
                "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                "delivery_fee": delivery_fee,
                "seller_grade": seller_grade,
            }
        except Exception as e:
            print(f"[상세 오류] {product_id}: {e}")
            return None

    # ── 내부 헬퍼 ─────────────────────────────────────────────
    @staticmethod
    def _safe(v, d="") -> str:
        if isinstance(v, dict):
            return v.get("#cdata-section", v.get("#text", d))
        return str(v).strip() if v is not None else d

    def _parse_grade(self, seller) -> str:
        if not seller:
            return "조회중"   # 목록 API에는 없음 — 관심 등록 시 상세 조회로 갱신
        s = self._safe
        # 가능한 모든 필드 시도
        raw = (s(seller.get("grade")) or s(seller.get("level"))
               or s(seller.get("sellerGrade")) or s(seller.get("rank"))
               or s(seller.get("rating")) or s(seller.get("star"))
               or s(seller.get("tier")) or "")
        if not raw:
            # seller 객체 안에 등급 관련 키가 있으면 출력
            all_keys = list(seller.keys()) if isinstance(seller, dict) else []
            print(f"[등급 미확인] seller keys: {all_keys}")
            return "- 미확인"
        return GRADE_MAP.get(raw.lower(), f"- {raw}")

    def _parse_deli(self, deli) -> int:
        if not deli:
            return 3000
        if isinstance(deli, (str, int)):
            raw = str(deli).replace(",","")
            return int(raw) if raw.isdigit() else 3000
        s = self._safe
        who = s(deli.get("who","")).upper()
        if who == "F":
            return 0
        fee_raw = s(deli.get("fee","0")).replace(",","")
        return int(fee_raw) if fee_raw.isdigit() else 3000

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

            # 첫 번째 아이템 전체 키 출력 (한 번만)
            if items:
                first_keys = list(items[0].keys())
                print(f"[목록 API 필드] {first_keys}")

            s = self._safe
            for item in items:
                state  = s(item.get("state"),"2")
                stock  = s(item.get("stock"),"999")
                status = "N" if state in ["3","4"] or stock=="0" else "Y"
                raw_price    = s(item.get("price","0")).replace(",","")
                delivery_fee = self._parse_deli(item.get("deli", {}))
                # 목록 API에 seller 있으면 파싱, 없으면 "조회중" (관심 등록 시 갱신)
                seller_raw   = item.get("seller", {})
                seller_grade = self._parse_grade(seller_raw) if seller_raw else "조회중"
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
