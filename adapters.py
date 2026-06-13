# adapters.py 내의 DomeameAdapter 수정 예시
from base_adapter import BaseWholesaleAdapter
from domeme_client import DomeameClient  # 방금 만든 클라이언트 불러오기

class DomeameAdapter(BaseWholesaleAdapter):
    def __init__(self, api_key=""):
        self.api_key = api_key
        self.site_name = "도매매"
        self.client = DomeameClient(api_key=self.api_key) # 실제 클라이언트 연결

    def get_products(self):
        # 가상 데이터 대신 실제 클라이언트의 fetch 함수를 호출!
        return self.client.fetch_product_list(category_code="1001")