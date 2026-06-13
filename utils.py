def calculate_target_price(supply_price, delivery_fee, platform_fee_rate, target_margin_rate):
    """
    기획서 마진 역산 공식:
    판매가 = (도매공급가 + 도매배송비) / (1 - (플랫폼수수료율 + 목표마진율))
    """
    # 분모가 0 이하가 되는 역마진/오류 방지
    if (1 - platform_fee_rate - target_margin_rate) <= 0:
        return 0

    sales_price = (supply_price + delivery_fee) / (1 - platform_fee_rate - target_margin_rate)

    # 10원 단위 절사 (예: 15432원 -> 15430원)
    return int(round(sales_price, -1))


def calculate_expected_profit(sales_price, supply_price, delivery_fee, platform_fee_rate):
    """
    예상 순수익 = 판매가 - (판매가 * 플랫폼수수료율) - 공급가 - 배송비
    """
    if sales_price == 0:
        return 0

    fee = sales_price * platform_fee_rate
    profit = sales_price - fee - supply_price - delivery_fee
    return int(profit)