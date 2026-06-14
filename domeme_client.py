import re
import requests
import json
import time

GRADE_DISPLAY = {
    "s":"⭐S등급","platinum":"⭐S등급",
    "a":"🔵A등급","gold":"🔵A등급",
    "b":"🟢B등급","silver":"🟢B등급",
    "c":"🟡C등급","bronze":"🟡C등급",
    "d":"🟠D등급","e":"🔴E등급","f":"🔴F등급",
    "1":"⭐1등급","2":"🔵2등급","3":"🟢3등급","4":"🟡4등급","5":"🟠5등급",
}


def _safe(v, d="") -> str:
    if isinstance(v, dict):
        return v.get("#cdata-section", v.get("#text", d))
    return str(v).strip() if v is not None else d


def _parse_price(raw_val) -> int:
    """★ 분석 보고서 보완: re.sub으로 숫자만 추출해 파싱 실패율 감소"""
    text = _safe(raw_val, "0")
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else 0


def _parse_grade(seller_obj) -> str:
    if not seller_obj:
        return ""
    if isinstance(seller_obj, str):
        raw = seller_obj.strip()
    else:
        raw = (_safe(seller_obj.get("grade"))
               or _safe(seller_obj.get("level"))
               or _safe(seller_obj.get("rank"))
               or _safe(seller_obj.get("rating"))
               or _safe(seller_obj.get("sellerGrade"))
               or _safe(seller_obj.get("star"))
               or _safe(seller_obj.get("tier"))
               or _safe(seller_obj.get("class"))
               or _safe(seller_obj.get("point"))
               or "")
        if not raw:
            raw = _safe(seller_obj)
    if not raw:
        return ""
    return GRADE_DISPLAY.get(raw.lower().strip(), raw)


def _parse_deli(deli) -> int:
    if not deli:
        return 3000
    if isinstance(deli, (str, int)):
        digits = re.sub(r"[^0-9]", "", str(deli))
        return int(digits) if digits else 3000
    who = _safe(deli.get("who", "")).upper()
    if who == "F":
        return 0
    digits = re.sub(r"[^0-9]", "", _safe(deli.get("fee", "0")))
    return int(digits) if digits else 3000


def _parse_image(item: dict, pid: str) -> str:
    for field in ["img", "image", "thumb", "thumbnail", "photo", "pic"]:
        val = _safe(item.get(field, ""))
        if val and val.startswith("http"):
            return val
    return f"https://img.domeggook.com/main/{pid}/1.jpg" if pid else ""


class DomeameClient:
    def __init__(self, api_key: str):
        self.api_key  = api_key
        self.base_url = "https://domeggook.com/ssl/api/"

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
                if resp.status_code != 200:
                    print(f"[{site_name}] HTTP {resp.status_code}")
                    break
                items = self._parse_list(resp.text, site_name, dump=first)
                first = False
                if not items:
                    break
                all_results.extend(items)
                print(f"[{site_name}] pg={pg} → {len(items)}개")
                if len(items) < page_size:
                    break
                if pg < max_pages:
                    time.sleep(0.3)
            except Exception as e:
                print(f"[{site_name}] 오류: {e}")
                break
        return all_results

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

            seller_raw = item.get("seller", {})
            print(f"[상세 전체키] {list(item.keys())}")
            print(f"[상세 seller원문] {json.dumps(seller_raw, ensure_ascii=False)}")

            state  = _safe(item.get("state", "2"))
            stock  = _safe(item.get("stock", "999"))
            status = "N" if state in ["3","4"] or stock=="0" else "Y"
            delivery  = _parse_deli(item.get("deli", {}))
            grade     = _parse_grade(seller_raw)
            image_url = _parse_image(item, product_id)
            price     = _parse_price(item.get("price", "0"))

            return {
                "status":       status,
                "supply_price": price,
                "delivery_fee": delivery,
                "seller_grade": grade,
                "image_url":    image_url,
            }
        except Exception as e:
            print(f"[상세 오류] {product_id}: {e}")
            return None

    def batch_fetch_grades(self, products: list[dict], limit: int = 15) -> list[dict]:
        updated = []
        fetched = 0
        for prod in products:
            if (fetched < limit
                    and prod.get("site") in ["도매매","도매꾹"]
                    and not prod.get("seller_grade","")):
                detail = self.fetch_item_detail(str(prod["product_id"]))
                if detail:
                    for k, v in detail.items():
                        if v or v == 0:
                            prod = {**prod, k: v}
                fetched += 1
                time.sleep(0.25)
            updated.append(prod)
        print(f"[배치] {fetched}개 상세 조회 완료")
        return updated

    def _parse_list(self, raw: str, site_name: str, dump=False) -> list[dict]:
        results = []
        try:
            data  = json.loads(raw)
            err   = data.get("domeggook",{}).get("error")
            if err:
                print(f"[API Error] {site_name}: {err}")
                return []
            items = data.get("domeggook",{}).get("list",{}).get("item",[])
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                return []

            if dump and items:
                print(f"[목록 전체키] {list(items[0].keys())}")
                print(f"[목록 seller] {json.dumps(items[0].get('seller','없음'), ensure_ascii=False)}")

            for item in items:
                state  = _safe(item.get("state","2"))
                stock  = _safe(item.get("stock","999"))
                status = "N" if state in ["3","4"] or stock=="0" else "Y"
                pid    = _safe(item.get("no",""))
                price  = _parse_price(item.get("price","0"))   # ★ re.sub 방식
                delivery  = _parse_deli(item.get("deli", {}))
                grade     = _parse_grade(item.get("seller", {}))
                image_url = _parse_image(item, pid)
                results.append({
                    "site":         site_name,
                    "product_id":   pid,
                    "name":         _safe(item.get("title","이름 없음")),
                    "supply_price": price,
                    "delivery_fee": delivery,
                    "status":       status,
                    "seller_grade": grade,
                    "image_url":    image_url,
                })
        except json.JSONDecodeError as e:
            print(f"[JSON 파싱 오류] {e}")
        except Exception as e:
            print(f"[파싱 오류] {e}")
        return results
