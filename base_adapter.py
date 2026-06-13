class BaseWholesaleAdapter:
    def get_products(self):
        """
        각 도매 사이트의 API를 호출하여 아래와 같은 표준 딕셔너리 리스트로 반환해야 합니다.
        [{'site': '...', 'product_id': '...', 'name': '...', 'supply_price': 0, 'delivery_fee': 0, 'status': 'Y/N'}]
        """
        raise NotImplementedError("하위 클래스에서 이 메서드를 구현해야 합니다.")