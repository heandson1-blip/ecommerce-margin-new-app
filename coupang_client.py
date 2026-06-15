"""
coupang_client.py — 쿠팡 Open API 클라이언트
- 상품 조회/등록/수정
- 발주서 조회 (송장 처리용)
- 송장 업로드

Secrets: COUPANG_ACCESS_KEY, COUPANG_SECRET_KEY, COUPANG_VENDOR_ID
API 문서: https://developers.coupangcorp.com
"""
import hmac
import hashlib
import requests
import json
import datetime


def _sign(method, path, query, secret_key, access_key):
    """쿠팡 API HMAC-SHA256 서명 생성"""
    datetime_str = datetime.datetime.utcnow().strftime("%y%m%d")
    time_str      = datetime.datetime.utcnow().strftime("%H%M%S")
    message = datetime_str + time_str + method + path + query
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={datetime_str}T{time_str}Z, signature={signature}"
    )


class CoupangClient:
    BASE = "https://api-gateway.coupang.com"

    def __init__(self, access_key: str, secret_key: str, vendor_id: str):
        self.access_key = access_key
        self.secret_key = secret_key
        self.vendor_id  = vendor_id

    def _request(self, method: str, path: str, params: dict = None, body: dict = None):
        query = ""
        if params:
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        auth = _sign(method, path, query, self.secret_key, self.access_key)
        headers = {
            "Authorization": auth,
            "Content-Type":  "application/json;charset=UTF-8",
        }
        url = self.BASE + path
        if query:
            url += "?" + query
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=15)
            elif method == "POST":
                r = requests.post(url, headers=headers,
                                  data=json.dumps(body or {}), timeout=15)
            elif method == "PUT":
                r = requests.put(url, headers=headers,
                                 data=json.dumps(body or {}), timeout=15)
            else:
                return {}
            print(f"[쿠팡 API] {method} {path} → {r.status_code}")
            if r.status_code in [200, 201]:
                return r.json()
            print(f"[쿠팡 API 오류] {r.text[:300]}")
        except Exception as e:
            print(f"[쿠팡 API 예외] {e}")
        return {}

    # ── 카테고리 조회 ────────────────────────────────────────
    def get_categories(self, category_id: int = 1) -> dict:
        """카테고리 조회 (상품 등록 시 필요)"""
        return self._request("GET", f"/v2/providers/seller_api/apis/api/v1/marketplace/categories/{category_id}")

    # ── 상품 등록 ────────────────────────────────────────────
    def create_product(self, product_data: dict) -> dict:
        """
        상품 등록
        product_data 최소 필수 필드:
        - vendorId, displayCategoryCode, sellerProductName
        - vendorUserId, saleStartedAt, saleEndedAt, displayProductName
        - productGroup, delivery, returnCenterCode
        - items (가격/재고/이미지)
        """
        path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        return self._request("POST", path, body=product_data)

    def build_product_body(self,
                           name: str,
                           category_code: int,
                           price: int,
                           stock: int,
                           image_urls: list[str],
                           description: str = "",
                           brand: str = "",
                           delivery_type: str = "NONE_TRACEABLE") -> dict:
        """상품 등록용 body 빌더 (기본 단일옵션 상품)"""
        now = datetime.datetime.now()
        sale_start = now.strftime("%Y-%m-%dT%H:%M:%S")
        sale_end   = (now + datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
        return {
            "vendorId":            self.vendor_id,
            "displayCategoryCode": category_code,
            "sellerProductName":   name,
            "vendorUserId":        self.vendor_id,
            "saleStartedAt":       sale_start,
            "saleEndedAt":         sale_end,
            "displayProductName":  name,
            "brand":               brand,
            "productGroup":        "일반상품",
            "delivery": {
                "outboundShippingTimeDay": 1,
                "deliveryCompanyCode":     "CJ대한통운",
                "deliveryChargeType":      "FREE",
                "deliveryCharge":          0,
                "freeShipOverAmount":      0,
                "returnShippingCharge":    2500,
                "unionDeliveryType":       "UNION_DELIVERY",
            },
            "items": [{
                "itemName":       "기본",
                "originalPrice":  int(price * 1.1),
                "salePrice":      price,
                "maximumBuyCount": 99,
                "maximumBuyForPerson": 0,
                "unitCount":      1,
                "adultOnly":      "EVERYONE",
                "taxType":        "TAX",
                "parallelImported": "NOT_PARALLEL_IMPORTED",
                "externalVendorSku": "",
                "barcode":        "",
                "emptyBarcode":   True,
                "emptyBarcodeReason": "없음",
                "images": [{"imageOrder": i, "imageType": "REPRESENTATION" if i==0 else "DETAIL",
                             "cdnPath": url, "vendorPath": url}
                           for i, url in enumerate(image_urls[:10])],
                "contents": [{"contentsType": "IMAGE", "cdnPath": url, "vendorPath": url}
                             for url in image_urls[:5]],
                "searchTags":    [],
                "notices":       [],
                "attributes":    [],
                "certifications": [],
                "requiredDocuments": [],
                "extraProperties": [],
                "itemInventories": [{"vendorItemPackageName": "기본",
                                     "vendorItemName": "기본",
                                     "originalPrice": int(price*1.1),
                                     "salePrice": price,
                                     "qty": stock}],
            }],
        }

    # ── 발주서 조회 ──────────────────────────────────────────
    def get_orders(self, status: str = "ACCEPT", date: str = None) -> list[dict]:
        """
        발주서 조회
        status: ACCEPT(신규주문), DEPARTURE(출고완료), DELIVERING(배송중), DELIVERED(배송완료)
        date: YYYY-MM-DD (없으면 오늘)
        """
        if not date:
            date = datetime.datetime.now().strftime("%Y-%m-%d")
        params = {
            "vendorId":   self.vendor_id,
            "status":     status,
            "orderedAt":  date,
            "maxPerPage": 50,
            "pageIndex":  1,
        }
        path = f"/v2/providers/seller_api/apis/api/v1/vendor-items/orders/shipment-boxes"
        data = self._request("GET", path, params=params)
        return data.get("data", {}).get("content", [])

    # ── 송장 업로드 ──────────────────────────────────────────
    def upload_tracking(self, order_id: str, tracking_number: str,
                        courier_code: str = "KGB") -> dict:
        """
        송장 번호 업로드
        courier_code: KGB(로젠), CJ(CJ대한통운), LOTTE(롯데), HANJIN(한진), POST(우체국)
        """
        path = (f"/v2/providers/seller_api/apis/api/v1/vendor-items/orders/"
                f"shipment-boxes/{order_id}/tracking-numbers/{tracking_number}")
        body = {"deliveryCompanyCode": courier_code}
        return self._request("PUT", path, body=body)

    # ── 정산 조회 ────────────────────────────────────────────
    def get_settlements(self, start_date: str, end_date: str) -> list[dict]:
        """정산 내역 조회"""
        params = {
            "vendorId":  self.vendor_id,
            "startDate": start_date,
            "endDate":   end_date,
        }
        path = "/v2/providers/seller_api/apis/api/v1/vendor-items/orders/settled"
        data = self._request("GET", path, params=params)
        return data.get("data", [])
