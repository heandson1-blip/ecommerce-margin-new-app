"""
sheets_client.py — Google Sheets 연동
일일 주문/송장/정산 데이터를 구글 시트에 자동 기록

Secrets:
  GOOGLE_SERVICE_ACCOUNT_JSON: 서비스 계정 JSON 전체 내용 (문자열)
  GOOGLE_SHEET_ID: 구글 시트 ID (URL에서 /d/ 이후 값)

설정 방법:
1. Google Cloud Console → IAM → 서비스 계정 생성
2. JSON 키 다운로드
3. 구글 시트 → 공유 → 서비스 계정 이메일 편집자 권한 추가
4. Streamlit Secrets에 JSON 내용과 시트 ID 등록
"""
import json
from datetime import datetime


def get_sheets_client(service_account_json: str):
    """gspread 클라이언트 초기화"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        info = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(
            info,
            scopes=["https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive"],
        )
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[Sheets] 초기화 오류: {e}")
        return None


class SheetsManager:
    SHEET_ORDERS      = "주문_송장"
    SHEET_INVENTORY   = "소싱_관심상품"
    SHEET_SETTLEMENT  = "정산_일별"
    SHEET_KEYWORDS    = "키워드_분석"

    def __init__(self, service_account_json: str, sheet_id: str):
        self.gc       = get_sheets_client(service_account_json)
        self.sheet_id = sheet_id
        self._book    = None

    def _book(self):
        if self._book is None and self.gc:
            try:
                self._book = self.gc.open_by_key(self.sheet_id)
            except Exception as e:
                print(f"[Sheets] 시트 열기 오류: {e}")
        return self._book

    def _get_or_create_worksheet(self, name: str, headers: list[str]):
        book = self._book()
        if not book:
            return None
        try:
            ws = book.worksheet(name)
        except Exception:
            ws = book.add_worksheet(title=name, rows=1000, cols=len(headers))
            ws.append_row(headers)
        return ws

    # ── 주문/송장 기록 ───────────────────────────────────────
    def log_orders(self, orders: list[dict]) -> bool:
        """
        발주서 목록을 시트에 기록
        orders: 쿠팡 get_orders() 반환값
        """
        headers = ["날짜","주문번호","상품명","수량","구매자","연락처","주소","송장번호","택배사","상태"]
        ws = self._get_or_create_worksheet(self.SHEET_ORDERS, headers)
        if not ws or not orders:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        for o in orders:
            rows.append([
                today,
                str(o.get("shipmentBoxId","")),
                o.get("vendorItemName",""),
                o.get("shippingCount",""),
                o.get("ordererName",""),
                o.get("ordererPhone",""),
                o.get("deliveryAddress",""),
                o.get("trackingNumber",""),
                o.get("deliveryCompanyCode",""),
                o.get("status",""),
            ])
        try:
            ws.append_rows(rows)
            print(f"[Sheets] 주문 {len(rows)}건 기록 완료")
            return True
        except Exception as e:
            print(f"[Sheets] 기록 오류: {e}")
            return False

    # ── 관심 상품 동기화 ─────────────────────────────────────
    def sync_sourcing_products(self, products: list[dict]) -> bool:
        """소싱 관심 상품 목록을 시트에 동기화"""
        headers = ["날짜","상품명","소싱업체","상품번호","공급가","배송비","추천판매가","마진율","업체등급","상태"]
        ws = self._get_or_create_worksheet(self.SHEET_INVENTORY, headers)
        if not ws or not products:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        for p in products:
            rows.append([
                today,
                p.get("name",""),
                p.get("site",""),
                str(p.get("product_id","")),
                p.get("supply_price",0),
                p.get("delivery_fee",0),
                p.get("target_price",0),
                f"{p.get('margin_rate',0):.1f}%",
                p.get("seller_grade",""),
                p.get("status",""),
            ])
        try:
            ws.clear()
            ws.append_row(headers)
            ws.append_rows(rows)
            print(f"[Sheets] 관심상품 {len(rows)}개 동기화 완료")
            return True
        except Exception as e:
            print(f"[Sheets] 동기화 오류: {e}")
            return False

    # ── 키워드 분석 기록 ─────────────────────────────────────
    def log_keyword_analysis(self, keyword: str, platform: str, data: dict) -> bool:
        """키워드 분석 결과 기록"""
        headers = ["날짜","키워드","플랫폼","지표","값"]
        ws = self._get_or_create_worksheet(self.SHEET_KEYWORDS, headers)
        if not ws:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        rows = [[today, keyword, platform, k, str(v)] for k, v in data.items()]
        try:
            ws.append_rows(rows)
            return True
        except Exception as e:
            print(f"[Sheets] 키워드 기록 오류: {e}")
            return False

    # ── 일별 정산 기록 ───────────────────────────────────────
    def log_settlement(self, settlements: list[dict]) -> bool:
        headers = ["날짜","플랫폼","주문번호","상품명","판매가","수수료","정산금","정산일"]
        ws = self._get_or_create_worksheet(self.SHEET_SETTLEMENT, headers)
        if not ws or not settlements:
            return False
        rows = []
        for s in settlements:
            rows.append([
                s.get("settledDate", datetime.now().strftime("%Y-%m-%d")),
                "쿠팡",
                s.get("orderId",""),
                s.get("productName",""),
                s.get("salePrice",0),
                s.get("commissionFee",0),
                s.get("settlementAmount",0),
                s.get("paymentDate",""),
            ])
        try:
            ws.append_rows(rows)
            return True
        except Exception as e:
            print(f"[Sheets] 정산 기록 오류: {e}")
            return False
