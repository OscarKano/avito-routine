"""Цена для Авито и Telegram (одна и та же) из цены поставщика.

Считаем от желаемой чистой прибыли: с продажи Авито берёт комиссию, плюс
мы даём скидку на доставку. Настройки — в .env (см. config.py).

Проверка: цена 3990 → комиссия 319, скидка на доставку 90, итого 3581;
при закупке 2800 прибыль 781.
"""

import math

import config


def avito_price(supplier_price: int) -> int:
    raw = (supplier_price + config.PRICE_TARGET_PROFIT + config.PRICE_DELIVERY_SUBSIDY) / (
        1 - config.PRICE_AVITO_FEE
    )
    price = math.ceil((raw - 90) / 100) * 100 + 90  # вверх до ближайшего ...90
    return max(price, config.PRICE_MIN)


def net_profit(supplier_price: int, price: int) -> int:
    fee = round(price * config.PRICE_AVITO_FEE)
    return price - fee - config.PRICE_DELIVERY_SUBSIDY - supplier_price


if __name__ == "__main__":
    print("закупка -> цена, чистая прибыль")
    for s in (2500, 2600, 2700, 2800, 2900, 3000, 3200, 3300, 3500):
        p = avito_price(s)
        print(f"{s} -> {p}, прибыль {net_profit(s, p)}")
