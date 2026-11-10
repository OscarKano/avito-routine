"""
«💬 Шаблоны ответов» покупателям (идея №25, «надоедает писать»). Нажал на шаблон — бот присылает текст блоком с кнопкой
«Копировать», остаётся вставить в чат Авито. Шаблоны лежат в data/reply_templates.json, меняются прямо в боте:
«✏️ Изменить» -> выбрать шаблон -> прислать новый текст; «➕ Новый» -> первая строка — название, дальше текст.

Ссылок на Telegram в шаблонах нет специально: в чатах Авито их блокируют.
"""

import json
import html
from datetime import datetime, timedelta

import config

FILE = config.DATA_DIR / "reply_templates.json"
AWAIT = config.DATA_DIR / "reply_templates_await.json"  # ждём от владельца текст шаблона (живёт 15 минут)

DEFAULT = [
    {"title": "Есть размер?", "text": "Здравствуйте! Сейчас уточню наличие вашего размера и напишу в течение 10–15 минут."},
    {"title": "Размер есть", "text": "Ваш размер есть в наличии ✅ Оформляйте заказ через кнопку «Купить с доставкой» — "
                                     "отправлю в ближайшее время."},
    {"title": "Размера нет", "text": "К сожалению, этого размера сейчас нет 😔 Могу предложить похожие модели — "
                                     "посмотрите другие объявления в моём профиле."},
    {"title": "Как заказать", "text": "Оформляйте через кнопку «Купить с доставкой» в объявлении. Оплата идёт через Авито: "
                                      "деньги придут мне только после того, как вы получите и проверите пару. "
                                      "Перед заказом напишите размер — подтвержу наличие."},
    {"title": "Доставка, сроки", "text": "Отправляем по всей России через Авито Доставку. Срок зависит от города — точный "
                                         "Авито показывает при оформлении, обычно 3–7 дней."},
    {"title": "Можно проверить?", "text": "Да, в пункте выдачи можно осмотреть пару. Если что-то не так — можно отказаться "
                                          "прямо там, деньги вернутся."},
    {"title": "Подбор размера", "text": "Модель соответствует размеру. Если сомневаетесь — измерьте длину стопы от пятки "
                                        "до большого пальца и напишите мне в сантиметрах, подскажу."},
    {"title": "Оригинал?", "text": "Это качественная реплика (качество люкс), не оригинал — поэтому цена ниже магазинной. "
                                   "Все фото и видео — реальной пары."},
    {"title": "Скидка?", "text": "Цена уже ниже рынка, но при заказе двух пар сделаю скидку. Какой размер нужен?"},
    {"title": "Отправил", "text": "Спасибо за заказ! Пара отправлена, трек-номер: … Если будут вопросы — пишите."},
    {"title": "Попросить отзыв", "text": "Спасибо, что выбрали нас! Если всё понравилось — буду очень благодарен за отзыв "
                                         "на Авито, это сильно помогает 🙏"},
]


def load() -> list[dict]:
    if not FILE.exists():
        save(DEFAULT)
    return json.loads(FILE.read_text(encoding="utf-8"))


def save(items: list[dict]) -> None:
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def view(conn=None) -> tuple[str, list]:
    items = load()
    btns = [b(f"💬 {t['title']}", f"tp:s:{i}") for i, t in enumerate(items)]
    rows = [btns[k:k + 2] for k in range(0, len(btns), 2)]
    rows.append([b("✏️ Изменить", "tp:e"), b("➕ Новый", "tp:n"), b("🗑 Удалить", "tp:d")])
    rows.append([b("⬅️ Меню", "am:menu")])
    return ("<b>💬 Шаблоны ответов</b>\n\nНажми — пришлю текст с кнопкой «Копировать», вставишь в чат Авито.", rows)


def pick(action: str, label: str) -> tuple[str, list]:
    items = load()
    rows = [[b(f"{label} {t['title']}", f"tp:{action}:{i}")] for i, t in enumerate(items)]
    return "Какой шаблон?", rows + [[b("⬅️ Назад", "am:templates")]]


def set_await(kind: str, i: int | None = None) -> None:
    AWAIT.write_text(json.dumps({"kind": kind, "i": i, "until": (datetime.now() + timedelta(minutes=15)).isoformat()}),
                     encoding="utf-8")


def awaiting() -> dict | None:
    if not AWAIT.exists():
        return None
    a = json.loads(AWAIT.read_text(encoding="utf-8"))
    if datetime.fromisoformat(a["until"]) < datetime.now():
        AWAIT.unlink(missing_ok=True)
        return None
    return a


def handle_input(text: str) -> str:
    """Текст от владельца, пока ждём шаблон. Возвращает ответ для чата."""
    a = awaiting()
    AWAIT.unlink(missing_ok=True)
    if not a:
        return ""
    if text.strip().lower() in ("отмена", "cancel", "стоп"):
        return "Ок, шаблоны не менял."
    items = load()
    if a["kind"] == "edit" and a["i"] is not None and a["i"] < len(items):
        items[a["i"]]["text"] = text.strip()
        save(items)
        return f"✅ Шаблон «{items[a['i']]['title']}» обновлён."
    if a["kind"] == "new":
        first, _, rest = text.strip().partition("\n")
        if not rest.strip():
            return "Нужно две части: первая строка — название, со второй — сам текст. Нажми «➕ Новый» ещё раз."
        items.append({"title": first.strip()[:30], "text": rest.strip()})
        save(items)
        return f"✅ Добавил шаблон «{first.strip()[:30]}»."
    return ""


def handle(call, cq: dict, chat_id: int, msg_id: int, data: str) -> None:
    """Кнопки tp:… (call — bot.call)."""
    parts = data.split(":")
    items = load()
    note = ""
    if parts[1] == "s" and int(parts[2]) < len(items):
        t = items[int(parts[2])]
        call("sendMessage", {"chat_id": chat_id, "text": f"<pre>{html.escape(t['text'])}</pre>", "parse_mode": "HTML"})
        note = "Скопируй кнопкой в углу блока"
    elif parts[1] == "rev":  # из уведомления «клиент забрал» — шаблон с просьбой об отзыве
        t = next((x for x in items if "отзыв" in x["title"].lower()), None)
        text = t["text"] if t else DEFAULT[-1]["text"]
        call("sendMessage", {"chat_id": chat_id, "text": f"<pre>{html.escape(text)}</pre>", "parse_mode": "HTML"})
        note = "Скопируй и отправь покупателю в чат Авито"
    elif parts[1] in ("e", "d") and len(parts) == 2:
        text, rows = pick(parts[1], "✏️" if parts[1] == "e" else "🗑")
        call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text,
                                 "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False)})
    elif parts[1] == "e" and int(parts[2]) < len(items):
        set_await("edit", int(parts[2]))
        t = items[int(parts[2])]
        call("sendMessage", {"chat_id": chat_id, "parse_mode": "HTML", "text":
             f"Пришли новый текст для «{html.escape(t['title'])}» одним сообщением (или «отмена»). Сейчас там:\n\n"
             f"<pre>{html.escape(t['text'])}</pre>"})
    elif parts[1] == "n":
        set_await("new")
        call("sendMessage", {"chat_id": chat_id, "text": "Пришли новый шаблон одним сообщением: первая строка — название "
                             "(коротко, для кнопки), со второй — сам текст. Или «отмена»."})
    elif parts[1] == "d" and int(parts[2]) < len(items):
        gone = items.pop(int(parts[2]))
        save(items)
        text, rows = view()
        call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML",
                                 "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False)})
        note = f"Удалил «{gone['title']}»"
    call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": note})
