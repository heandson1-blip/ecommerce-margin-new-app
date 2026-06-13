import requests
import json

class DomeameClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://domeggook.com/ssl/api/"

    def fetch_product_list(self, market="supply", keyword="", category_code="0000"):
        site_name = "도매매" if market == "supply" else "도매꾹"
        print(f"[API 호출] {site_name} 서버 라이브 통신 중... (코드: {category_code}, 키워드: {keyword})")

        params = {
            "ver": "4.1", "mode": "getItemList", "aid": self.api_key,
            "market": market, "om": "json", "sz": 50,
        }
        if category_code and category_code != "0000":
            params["ca"] = category_code
        if keyword:
            params["kw"] = keyword

        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            if response.status_code == 200:
                return self._parse_json_to_standard(response.text, site_name)
            else:
                print(f"[Error] API 호출 실패 (상태 코드: {response.status_code})")
                return []
        except requests.exceptions.RequestException as e:
            print(f"[Error] 통신 예외 발생: {e}")
            return []

    def _parse_json_to_standard(self, json_data, site_name):
        standard_list = []
        try:
            data = json.loads(json_data)
            if "domeggook" in data and "error" in data["domeggook"]:
                print(f"[API Error] {data['domeggook']['error']['message']}")
                return []

            items = data.get("domeggook", {}).get("list", {}).get("item", [])
            if isinstance(items, dict): items = [items]

            # 💡 [핵심 보정] 도매매 특유의 XML CDATA 객체 안전 변환 함수
            def get_safe_text(value, default=""):
                if isinstance(value, dict):
                    # #cdata-section 이나 #text에 실제 상품명이 들어있으므로 이를 추출
                    return value.get("#cdata-section", value.get("#text", default))
                return str(value) if value is not None else default

            for item in items:
                state_val = get_safe_text(item.get("state"), "2")
                stock_val = get_safe_text(item.get("stock"), "999")

                # 품절/판매중지 판별 (상태 3:품절, 4:판매중지 또는 재고 0)
                if state_val in ["3", "4"] or stock_val == "0":
                    status = "N"
                else:
                    status = "Y"

                raw_price = get_safe_text(item.get("price", "0")).replace(",", "")
                name_val = get_safe_text(item.get("title"), "이름 없음") # 객체 해제 처리 적용
                prod_id_val = get_safe_text(item.get("no"), "")

                product = {
                    "site": site_name,
                    "product_id": prod_id_val,
                    "name": name_val,
                    "supply_price": int(raw_price) if raw_price.isdigit() else 0,
                    "delivery_fee": 3000,
                    "status": status
                }
                standard_list.append(product)
            print(f"[System] {site_name} 라이브 상품 {len(standard_list)}개 파싱 완료.")
        except Exception as e:
            print(f"[Error] 데이터 파싱 실패: {e}")
        return standard_list