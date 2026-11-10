"""Кнопки карточки модели в личке бота — общие для сводки (send_digest) и слушателя (bot_listener).

  new       -> [✅ Взять] [❌ Убрать]
  approved  -> [✅ ВЗЯТО (нажми, чтобы отменить)]
  rejected  -> [❌ УБРАНО (нажми, чтобы вернуть)]
  под ними всегда строка [🖼 Главное фото] — выбор первого фото для Авито (cover).
"""

import json

import config

MAX_PHOTOS = 10  # столько фото уходит на Авито (schedule_queue.upload_media берёт первые 10)


def card_keyboard(cid: int, status: str, cover: int | None = None) -> str:
    """04.11: ok/no/cv есть при ЛЮБОМ статусе. Telegram сам отказывает в нажатии кнопки, которой уже нет на сервере: если телефон
    не получил правку карточки и показывает старые кнопки, нажатие молча не доходит до бота («не нажимается»)."""
    first = [{"text": "✅ ВЗЯТО" if status == "approved" else "✅ Взять", "callback_data": f"ok:{cid}"},
             {"text": "❌ УБРАНО" if status == "rejected" else "❌ Убрать", "callback_data": f"no:{cid}"}]
    label = f"🖼 Главное фото: №{cover}" if cover else "🖼 Главное фото"
    return json.dumps({"inline_keyboard": [first, [{"text": label, "callback_data": f"cv:{cid}"}]]})


def photo_numbers(cid: int) -> list[int]:
    """Номера фото (как на листе sheet.jpg), которые уходят на Авито: первые MAX_PHOTOS по порядку."""
    files = sorted((config.DATA_DIR / "candidates" / str(cid) / "photos").glob("*.jpg"))[:MAX_PHOTOS]
    return [int(p.stem) for p in files if p.stem.isdigit()]


def picker_keyboard(cid: int, cover: int | None = None) -> str:
    nums = photo_numbers(cid)
    buttons = [{"text": f"✅ {n}" if n == cover else str(n), "callback_data": f"cvs:{cid}:{n}"} for n in nums]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
    rows.append([{"text": "✅ Взять", "callback_data": f"ok:{cid}"}, {"text": "❌ Убрать", "callback_data": f"no:{cid}"}])
    rows.append([{"text": "🔄 Показать заново", "callback_data": f"cv:{cid}"}, {"text": "🔙 Отмена", "callback_data": f"cvb:{cid}"}])
    return json.dumps({"inline_keyboard": rows})


def first_clean_photo(cid: int, hands: list[int]):
    """Фото для карточки в ЛИЧНОЙ сводке бота (не для канала!) — предпочитаем без рук, но если рука
    есть на всех фото (бывает у постов "сравнение цветов на одной руке"), берём первое любое: это лишь
    превью для твоего решения "взять/убрать", не публичный пост, наличие руки тут не критично.
    Молчаливая потеря кандидата хуже, чем рука на превью."""
    photos = sorted((config.DATA_DIR / "candidates" / str(cid) / "photos").glob("*.jpg"))
    for p in photos:
        if int(p.stem) not in hands:
            return p
    return photos[0] if photos else None


def with_cover(cid: int, links: list[str], cover: int | None) -> list[str]:
    """Ссылки на фото для Авито: выбранное фото (по номеру) ставим первым, остальные — по порядку."""
    if not cover:
        return links
    files = sorted((config.DATA_DIR / "candidates" / str(cid) / "photos").glob("*.jpg"))[:MAX_PHOTOS]
    for i, p in enumerate(files):
        if p.stem.isdigit() and int(p.stem) == cover and i < len(links):
            return [links[i]] + links[:i] + links[i + 1:]
    return links
