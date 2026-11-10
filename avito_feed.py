"""Сборка XML-файла автозагрузки Авито (Мужская/Женская обувь → Кроссовки; «Ботинки …» → Ботинки и полуботинки).

Поля и допустимые значения — по документации Авито (категория 100368) и
шаблону пользователя. Один Size на объявление (всегда 42), все размеры —
в описании. Цена та же, что в Telegram (pricing.py).
"""

import json
from xml.sax.saxutils import escape

import config

PHONE = "89046303486"
ADDRESS = "Москва, Тверская ул., 19"
DEFAULT_SIZE = "42"
DELIVERY = ["ПВЗ", "Постамат", "Курьер"]
DELIVERY_SUBSIDY = config.PRICE_DELIVERY_SUBSIDY  # скидка на доставку, ₽


SUPPLIER_INSOLES = {"36": "23"}  # длина стельки для 36 — у пользователя в таблице нет, взято из постов поставщиков (36-23 см)
GENDER = {  # значения по шаблонам Авито: мужской (100368) и женский "Кроссовки и кеды"
    "male": {"goods_type": "Мужская обувь", "apparel": "Кроссовки", "size": "42"},
    "female": {"goods_type": "Женская обувь", "apparel": "Кроссовки и кеды", "size": "38"},
}
# название «Ботинки …» -> раздел «Ботинки и полуботинки» (у мужских и женских значение одно, остальные поля те же —
# сверено по /autoload/v1/user-docs 30.09.2026). Кроме двух Timberland Chukka: они вышли 28.09 ещё в «Кроссовках», а
# раздел у живого объявления Авито менять не даёт — пусть там и остаются
BOOTS = "Ботинки и полуботинки"
# 07.11: Авито — «Страна происхождения товара» (CountryExpedition) станет обязательной с 15.11.2026 во всех 4 разделах
# обуви (warnings в /autoload/v1/user-docs/node/<раздел>/fields); без неё «автозагрузка перестанет работать». Пока
# пусто — тег не пишется (Авито ставит «Россия»); значение — после подтверждения владельца, сверка до/после
COUNTRY = ""
BOOTS_LEFT_IN_SNEAKERS = {"sf-c238", "sf-c239"}


def apparel(item: dict) -> str:
    if item["title"].startswith("Ботинки") and item["id"] not in BOOTS_LEFT_IN_SNEAKERS:
        return BOOTS
    return GENDER[item.get("gender", "male")]["apparel"]


def _insoles() -> dict:
    return {**SUPPLIER_INSOLES, **json.loads((config.DATA_DIR / "insole_user_table.json").read_text(encoding="utf-8"))}


def description_v2(item: dict) -> str:
    """19.10 (владелец: «может описания переделаем, более красивые?»): первые строки — то, что видно в превью и что
    решает покупку (примерка до оплаты, скидка за 2 пары, помощь с размером), дальше — блоки с эмодзи. Без простыни
    ключевых слов (Авито за это понижает). Пока — только для объявлений с фото-рамкой (тест, scripts/avito_photos.py)."""
    table = _insoles()
    sizes = "\n".join(f"{s} — {table[str(s)]} см" if str(s) in table else str(s) for s in item["sizes"])
    parts = [
        f"👟 {item['title']}",
        "✅ Примерка 15 минут в пункте выдачи — не подошло, просто не забираете\n"
        "✅ Скидка 10% при заказе от 2 пар\n"
        "✅ Помогу подобрать размер по длине стельки",
        item["intro"] + (("\n" + item["season_text"]) if item.get("season_text") else ""),
        "🔥 Почему стоит брать:\n" + "\n".join(b if b and not b[0].isalnum() else f"• {b}" for b in item["bullets"]),  # свои эмодзи — без «•»
    ]
    if item.get("pair_with"):
        parts.append("👖 Идеально с: " + item["pair_with"])
    parts += [
        f"📏 Размеры (длина стельки):\n{sizes}\nНапишите длину стопы в сантиметрах — подскажу размер.",
        "📦 Как купить:\n1. Напишите размер\n2. Подтверждаю наличие\n3. Оформляем через Авито Доставку и отправляем",
        "🚚 Доставка: Почта России / СДЭК / DPD / Яндекс Доставка / Авито / 5Post",
        "🔄 Возврат: брак — пересылку оплачиваем мы. Не подошёл — оплачивает покупатель.",
        "👟 Больше моделей — в профиле. Подписывайтесь — новинки каждый день!",
    ]
    return "\n\n".join(parts)


def description(item: dict) -> str:
    """Описание по шаблону пользователя. item: intro, bullets, pair_with, season_text, sizes."""
    if item.get("v2"):
        return description_v2(item)
    table = _insoles()
    sizes = "\n".join(f"{s} — {table[str(s)]} см" if str(s) in table else str(s) for s in item["sizes"])
    parts = [item["intro"]]
    if item.get("season_text"):
        parts.append(item["season_text"])
    parts.append("Почему стоит брать:\n" + "\n".join(item["bullets"]))
    if item.get("pair_with"):
        parts.append("Идеально с: " + item["pair_with"])
    parts.append(f"📏 Размеры:\n{sizes}\nУточните размер — напишите длину стельки в сантиметрах.")
    parts.append(
        "📦 КАК КУПИТЬ:\n"
        "Напишите размер\n"
        "Подтверждаю наличие\n"
        "Оформляем через Авито Доставку и отправляем"
    )
    parts.append("🚚 Доставка: Почта России / СДЭК / DPD / Яндекс Доставка / Авито / 5Post")
    parts.append("🔄 Возврат: брак — пересылку оплачиваем мы. Не подошёл — оплачивает покупатель.")
    parts.append("👟 Больше моделей — в профиле")
    return "\n\n".join(parts)


def ad_xml(item: dict, price: int, image_urls: list[str], video_url: str | None, video_cdata: bool = True,
           date_begin: str | None = None) -> str:
    """date_begin — время выхода объявления (ISO с часовым поясом): пока оно не наступило, Авито ждёт."""
    g = GENDER[item.get("gender", "male")]
    lines = [
        "  <Ad>",
        f"    <Id>{escape(item['id'])}</Id>",
        *([f"    <DateBegin>{date_begin}</DateBegin>"] if date_begin else []),
        f"    <Address>{escape(ADDRESS)}</Address>",
        f"    <ContactPhone>{PHONE}</ContactPhone>",
        "    <Category>Одежда, обувь, аксессуары</Category>",
        f"    <GoodsType>{g['goods_type']}</GoodsType>",
        f"    <ApparelType>{apparel(item)}</ApparelType>",
        "    <AdType>Товар приобретен на продажу</AdType>",
        f"    <Title>{escape(item['title'])}</Title>",
        f"    <Description><![CDATA[{description(item)}]]></Description>",
        f"    <Price>{price}</Price>",
        "    <Condition>Новое с биркой</Condition>",
        f"    <Brand>{escape(item['brand'])}</Brand>",
        f"    <Color>{escape(item['color'])}</Color>",
        f"    <Size>{g['size']}</Size>",
    ]
    materials = item.get("materials", ["Натуральный"])  # пользователь почти всегда ставит "Натуральный"
    lines.append("    <MaterialsOdezhda>" + "".join(f"<Option>{m}</Option>" for m in materials) + "</MaterialsOdezhda>")
    if item.get("season"):
        lines.append("    <Season>" + "".join(f"<Option>{s}</Option>" for s in item["season"]) + "</Season>")
    if COUNTRY:
        lines.append(f"    <CountryExpedition>{COUNTRY}</CountryExpedition>")
    lines.append("    <MultiItem>Нет</MultiItem>")
    lines.append("    <Delivery>" + "".join(f"<Option>{d}</Option>" for d in DELIVERY) + "</Delivery>")
    lines.append("    <TryOn>Можно примерить</TryOn>")
    lines.append(f"    <DeliverySubsidy>{DELIVERY_SUBSIDY}</DeliverySubsidy>")
    lines.append("    <Images>")
    lines += [f'      <Image url="{escape(u)}"/>' for u in image_urls[:10]]
    lines.append("    </Images>")
    if video_url:
        value = f"<![CDATA[{video_url}]]>" if video_cdata else escape(video_url)
        lines.append(f"    <VideoFileURL>{value}</VideoFileURL>")
    lines.append("  </Ad>")
    return "\n".join(lines)


def feed_xml(ads: list[str]) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n<Ads formatVersion="3" target="Avito.ru">\n' + "\n".join(ads) + "\n</Ads>\n"
