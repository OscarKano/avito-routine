"""
Чаты Авито в боте (владелец 28.10: «2 делай» — чатов на Авито 844, «я путаюсь, неудобно»). С подпиской «Расширенная»
Авито открыло API мессенджера (проверено 28.10: список чатов и сообщения читаются).

Новое сообщение покупателя -> карточка владельцу в бота: кто пишет, модель, цена, закупка, размерный ряд, поставщик
(кнопка на его пост — спросить наличие), что пишет покупатель и какой размер спрашивает (стельку в см переводим в
размер по data/insole_user_table.json). Кнопки — его же обычные ответы (сверено по 45 чатам 28.10): «Сейчас посмотрю»,
«43-й есть», «43-й разобрали», «Уточню утром», ответ по теме вопроса (оригинал/доставка/скидка — из «💬 Шаблонов»,
reply_templates.py), любой шаблон, свой текст. Отправляется ТОЛЬКО по нажатию; ссылки и контакты не пропускаем
(Авито за них блокирует). Покупатель написал ещё — приходит новая карточка, у старой кнопки убираются.

Опрос — из bot_listener примерно раз в минуту (poll). Слово «чаты» / кнопка «💬 Чаты» в меню — все, где покупатель
ждёт ответа за последние 3 дня. Первый запуск ничего не присылает, только запоминает текущие сообщения.

API: GET /messenger/v2/accounts/{uid}/chats, GET /messenger/v3/accounts/{uid}/chats/{id}/messages/,
POST /messenger/v1/accounts/{uid}/chats/{id}/messages {"message": {"text"}, "type": "text"}, POST …/chats/{id}/read.
"""

import re
import sys
import json
import html
import time
from datetime import datetime, timedelta

import requests

import config
import bot
import reply_templates
from avito_reviews import CONTACTS_RE

sys.path.insert(0, str(config.BASE_DIR / "scripts"))
from check_avito_items import get_access_token  # noqa: E402

API = "https://api.avito.ru/messenger"
STATE = config.DATA_DIR / "avito_chats.json"  # seen: чат -> последнее входящее, cards: карточки в боте
AWAIT = config.DATA_DIR / "avito_chats_await.json"  # ждём свой текст после «✏️ Свой текст» (живёт 15 минут)
WAIT_DAYS = 3
SHOW_MAX = 15
# 28.10 вечер, владелец: «нужна другая подписка за 6k» — на «Расширенной» Авито отдаёт вместо сообщений «Перейдите на
# подписку с API мессенджера» и не даёт отвечать. Выключено: ни карточек, ни кнопки в меню. Купит подписку -> True.
ENABLED = False

SIZE_RE = re.compile(r"(?<![\d.,])(3[4-9]|4[0-8])(?![\d.,])")
CM_RE = re.compile(r"(?<![\d.,])(2[2-9]|3[01])(?:[.,](\d))?\s*(?:см|cm|сантим)|стельк\w*\D{0,12}?(2[2-9]|3[01])(?:[.,](\d))?",
                   re.I)
# вопрос не про размер — ответ из шаблона с таким названием (шаблоны владелец правит в боте); порядок = приоритет
INTENTS = [(r"оригинал|реплик|копи[яюи]\b|паль\b|подделк|дубл[ьи]|люкс", "Оригинал?"),
           (r"скидк|торг|дешевл|уступ|последн\w* цен", "Скидка?"),
           (r"доставк|отправ|сколько (ид|ехать)|когда (при|будут)|срок|сдэк|cdek|почт|пвз|пункт", "Доставка, сроки"),
           (r"пример|осмотр|провер|вернуть|возврат", "Можно проверить?"),
           (r"маломер|большемер|в размер|размерн\w* сетк|подойд|какой размер", "Подбор размера"),
           (r"как (заказать|купить|оформить)|оформить заказ", "Как заказать")]
THANKS_RE = re.compile(r"спасибо|благодар|всего доброго|хорошо\b|^ок\b|понял|понятно|ясно", re.I)
PAID_RE = re.compile(r"оплатил|оформил|заказал|готово", re.I)  # «Оплатил» -> его «Заказ подтверждаю»
PAID_TEXT = "Заказ подтверждаю, спасибо! Отправим в ближайшее время."
YES_TAIL = "Можно оформлять заказ через «Купить с доставкой», размер я записал."

_token = {"value": None, "at": 0.0}
_uid = None


# ---------- Авито ----------

def headers() -> dict:
    if not _token["value"] or time.time() - _token["at"] > 6 * 3600:  # токен живёт сутки; опрос раз в минуту
        _token.update(value=get_access_token(), at=time.time())
    return {"Authorization": f"Bearer {_token['value']}"}


def uid() -> int:
    global _uid
    if not _uid:
        _uid = requests.get("https://api.avito.ru/core/v1/accounts/self", headers=headers(), timeout=30).json()["id"]
    return _uid


def fetch_chats(limit: int = 50, offset: int = 0) -> list[dict]:
    r = requests.get(f"{API}/v2/accounts/{uid()}/chats", headers=headers(), params={"limit": limit, "offset": offset},
                     timeout=30)
    if r.status_code == 401:
        _token["value"] = None
    r.raise_for_status()
    return r.json().get("chats") or []


def fetch_messages(chat: str, limit: int = 15) -> list[dict]:
    """Старые -> новые. 28.10: на нашей подписке Авито через раз отвечает 402 «Перейдите на подписку с API
    мессенджера» — повторяем; не вышло — пустой список (карточка соберётся из последнего сообщения чата)."""
    for attempt in range(4):
        r = requests.get(f"{API}/v3/accounts/{uid()}/chats/{chat}/messages/", headers=headers(), params={"limit": limit},
                         timeout=30)
        if r.status_code != 402:
            r.raise_for_status()
            return list(reversed(r.json().get("messages") or []))
        time.sleep(1.5)
    return []


def send(chat: str, text: str) -> str | None:
    """Отправить сообщение в чат Авито. None — получилось, иначе причина."""
    text = text.strip()
    if not text:
        return "пустой текст"
    if CONTACTS_RE.search(text):
        return "в тексте ссылка или контакт — Авито за такое блокирует, убери"
    try:
        for attempt in range(3):  # 402 бывает через раз (см. fetch_messages); 402 = Авито не принял, не отправлено
            r = requests.post(f"{API}/v1/accounts/{uid()}/chats/{chat}/messages", headers=headers(),
                              json={"message": {"text": text}, "type": "text"}, timeout=30)
            if r.status_code != 402:
                break
            time.sleep(1.5)
        if r.status_code == 402:
            return "Авито не пускает отправку с нашей подпиской — ответь через «🔗 Чат на Авито»"
        if not r.ok:
            return f"Авито ответил {r.status_code}: {r.text[:150]}"
        requests.post(f"{API}/v1/accounts/{uid()}/chats/{chat}/read", headers=headers(), timeout=30)
    except requests.RequestException as exc:
        return f"нет связи с Авито ({type(exc).__name__})"
    return None


def waiting(c: dict) -> bool:
    """Последнее слово за покупателем (не системное «заказ оформлен» и не просто «спасибо, всего доброго»)."""
    m = c.get("last_message") or {}
    text = ((m.get("content") or {}).get("text") or "").strip()
    thanks = len(text) < 80 and THANKS_RE.search(text) and not re.search(r"\?|есть|размер|когда|сколько", text, re.I)
    return m.get("direction") == "in" and m.get("type") != "system" and not thanks


# ---------- состояние ----------

def load() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"seen": {}, "cards": {}, "next": 1}


def save(st: dict) -> None:
    cut = (datetime.now() - timedelta(days=7)).isoformat()
    st["cards"] = {k: v for k, v in st["cards"].items() if v.get("ts", "") >= cut}
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


# ---------- карточка ----------

def model_info(conn, item: dict) -> dict:
    """Наша модель по объявлению: №, закупка, размеры, пост поставщика. Ручные объявления — по точному названию."""
    q = ("SELECT c.id, c.price, c.sizes, c.channel_id, c.msg_ids, c.channel_name FROM candidates c ")
    row = conn.execute(q + "JOIN publish_queue p ON p.candidate_id=c.id JOIN avito_stock s ON s.ad_id=p.ad_id "
                       "WHERE s.avito_id=?", (item.get("id"),)).fetchone()
    row = row or conn.execute(q + "WHERE c.title_final=? ORDER BY c.id DESC LIMIT 1", (item.get("title"),)).fetchone()
    if not row:  # ручное объявление: размерный ряд хотя бы из названия («… 37-44»)
        m = re.search(r"(3\d|4\d)\s*[-–]\s*(3\d|4\d)", item.get("title") or "")
        return {"sizes": list(range(int(m.group(1)), int(m.group(2)) + 1))} if m else {}
    sizes = sorted(json.loads(row[2] or "[]"))
    post = None
    if row[3] and str(row[3]).startswith("-100") and row[4]:
        post = f"https://t.me/c/{str(row[3])[4:]}/{json.loads(row[4])[0]}"
    return {"cid": row[0], "cost": row[1], "sizes": sizes, "post": post, "supplier": row[5]}


def size_from(texts: list[str]) -> tuple[str | None, str | None]:
    """(размер, стелька см) из вопросов покупателя. Стелька без размера -> размер по таблице владельца."""
    joined = " ".join(texts)
    cm, size = None, None
    m = CM_RE.search(joined)
    if m:
        whole, frac = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        cm = whole + (f".{frac}" if frac and frac != "0" else "")
        joined = joined[:m.start()] + " " + joined[m.end():]
    s = SIZE_RE.findall(joined)
    if s:
        size = s[0]
    elif cm:
        table = json.loads((config.DATA_DIR / "insole_user_table.json").read_text(encoding="utf-8"))
        fit = [k for k, v in sorted(table.items(), key=lambda kv: float(kv[1])) if float(v) >= float(cm) - 0.01]
        size = fit[0] if fit else None
    return size, cm


def make_card(conn, st: dict, c: dict) -> bool:
    """Карточка по чату -> владельцу. False — Telegram не ответил (повторим на следующем опросе)."""
    msgs = fetch_messages(c["id"])
    me = uid()
    tail, greeted = [], False
    for m in msgs:  # входящие после нашего последнего ответа
        if m.get("direction") == "out":
            tail = []
            greeted = greeted or time.time() - m.get("created", 0) < 12 * 3600
        elif m.get("type") != "system":
            t = (m.get("content") or {}).get("text") or {"image": "[фото]", "voice": "[голосовое]"}.get(m.get("type"), "[вложение]")
            tail.append(t.strip())
    tail = tail[-4:] or [((c.get("last_message") or {}).get("content") or {}).get("text") or "…"]
    item = ((c.get("context") or {}).get("value")) or {}
    info = model_info(conn, item)
    size, cm = size_from(tail)
    low = " ".join(tail).lower()
    intent = next((title for pat, title in INTENTS if re.search(pat, low)), None)
    if PAID_RE.search(low):
        intent = "Заказ подтверждаю"
    who = next((u.get("name") for u in c.get("users", []) if u.get("id") != me), None) or "Покупатель"
    lines = [f"💬 <b>{html.escape(who)}</b> · Авито",
             f"👟 <b>{html.escape(item.get('title') or 'объявление')}</b> · {html.escape(item.get('price_string') or '')}"]
    if info.get("cid"):
        rng = f"{info['sizes'][0]}–{info['sizes'][-1]}" if info["sizes"] else "?"
        lines.append(f"№{info['cid']} · размеры {rng} · закупка {info['cost'] or '?'} ₽ · {html.escape(info['supplier'] or '')}")
    lines.append("\n".join(f"<i>«{html.escape(t[:500])}»</i>" for t in tail))
    if size:
        out = info.get("sizes") and int(size) not in info["sizes"]
        lines.append(f"🔎 Спрашивает: <b>{size}</b>" + (f" (стелька {cm} см)" if cm else "")
                     + (" — ⚠️ такого размера в модели нет" if out else ""))
    k = str(st["next"])
    card = {"chat": c["id"], "base": "\n".join(lines), "size": size, "cm": cm, "intent": intent, "greeted": greeted,
            "sizes": info.get("sizes") or [], "post": info.get("post"), "sent": [], "ts": datetime.now().isoformat()}
    res = bot.call("sendMessage", {"chat_id": bot.owner_chat_id(), "text": render_text(card), "parse_mode": "HTML",
                                   "reply_markup": kb(buttons(k, card)), "disable_web_page_preview": "true"})
    if not res.get("ok"):
        return False
    for old_k, old in st["cards"].items():  # у прежней карточки этого чата — убираем кнопки, чтобы не путаться
        if old["chat"] == c["id"] and old.get("msg") and not old.get("closed"):
            old["closed"] = True
            bot.call("editMessageText", {"chat_id": bot.owner_chat_id(), "message_id": old["msg"], "parse_mode": "HTML",
                                         "text": render_text(old) + "\n⤵️ <i>покупатель написал ещё — карточка ниже</i>",
                                         "reply_markup": kb([links(old)])})
    card["msg"] = res["result"]["message_id"]
    st["cards"][k] = card
    st["next"] += 1
    return True


def render_text(card: dict) -> str:
    sent = "".join(f"\n✅ <i>{html.escape(s[:200])}</i>" for s in card["sent"])
    return card["base"] + sent


def b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def kb(rows: list) -> str:
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


def links(card: dict) -> list:
    row = [{"text": "🔗 Чат на Авито", "url": f"https://www.avito.ru/profile/messenger/channel/{card['chat']}"}]
    if card.get("post"):
        row.append({"text": "📦 Пост поставщика", "url": card["post"]})
    return row


def buttons(k: str, card: dict) -> list:
    sz = card.get("size")
    first = [b("👀 Сейчас посмотрю", f"ac:look:{k}")]
    if datetime.now().hour >= 21 or datetime.now().hour < 9:
        first.append(b("🌙 Уточню утром", f"ac:morn:{k}"))
    rows = [first, [b(f"✅ {sz}-й есть" if sz else "✅ Есть", f"ac:yes:{k}"),
                    b(f"❌ {sz}-й разобрали" if sz else "❌ Разобрали", f"ac:no:{k}")]]
    if card.get("intent"):
        rows.append([b(f"💬 {card['intent']}", f"ac:it:{k}")])
    rows.append([b("📋 Шаблоны", f"ac:tpl:{k}"), b("✏️ Свой текст", f"ac:own:{k}"), b("⏭ Не отвечать", f"ac:skip:{k}")])
    rows.append(links(card))
    return rows


def compose(what: str, card: dict, arg: str | None = None) -> str:
    hi = "" if card.get("greeted") else "Здравствуйте! "
    sz, cm = card.get("size"), card.get("cm")
    if what == "look":
        return "Сейчас посмотрю" if card.get("greeted") else "Здравствуйте, сейчас посмотрю"
    if what == "morn":
        return hi + "Уточню наличие завтра с утра и сразу вам напишу."
    if what == "yes":
        if sz and cm:
            return hi + f"Есть, на стельку {cm} см подойдёт {sz}-й ✅ {YES_TAIL}"
        return hi + (f"{sz}-й размер в наличии ✅ {YES_TAIL}" if sz else
                     "В наличии ✅ Можно оформлять заказ через «Купить с доставкой». Напишите размер — я запишу.")
    if what == "no":
        if sz and card.get("sizes") and int(sz) not in card["sizes"]:
            return hi + (f"К сожалению, эта модель идёт только в размерах {card['sizes'][0]}–{card['sizes'][-1]}. "
                         "Могу предложить другую модель.")
        return hi + (f"К сожалению, {sz}-й размер разобрали. Могу предложить другую модель." if sz else
                     "К сожалению, этот размер разобрали. Могу предложить другую модель.")
    if what == "it":
        if card["intent"] == "Заказ подтверждаю":
            return PAID_TEXT
        tpl = next((t["text"] for t in reply_templates.load() if t["title"] == card["intent"]), "")
        return (hi + tpl) if tpl else ""
    if what == "t":
        items = reply_templates.load()
        i = int(arg or -1)
        return (hi + items[i]["text"]) if 0 <= i < len(items) else ""
    return ""


# ---------- опрос и показ ----------

def poll(conn) -> int:
    """Новые сообщения покупателей -> карточки. Вызывает bot_listener раз в минуту; без связи — молча до следующего раза."""
    if not ENABLED:
        return 0
    try:
        chats = fetch_chats(50)
    except (requests.RequestException, SystemExit, KeyError, ValueError):
        return 0
    st = load()
    first_run = not st.get("init")
    sent = 0
    for c in chats:
        last = c.get("last_message") or {}
        if not waiting(c) or st["seen"].get(c["id"]) == last.get("id"):
            continue
        if first_run or time.time() - last.get("created", 0) > WAIT_DAYS * 86400:
            st["seen"][c["id"]] = last.get("id")
            continue
        try:
            ok = make_card(conn, st, c)
        except requests.RequestException:
            ok = False
        if not ok:
            break  # Telegram/Авито не ответил — этот и остальные чаты повторим на следующем опросе
        st["seen"][c["id"]] = last.get("id")
        sent += 1
    if first_run:
        st["init"] = datetime.now().isoformat(timespec="minutes")
        n = sum(1 for c in chats if waiting(c) and time.time() - (c.get("last_message") or {}).get("created", 0) < WAIT_DAYS * 86400)
        bot.call("sendMessage", {"chat_id": bot.owner_chat_id(), "text":
                 "💬 Чаты Авито теперь здесь: новое сообщение покупателя сразу придёт карточкой с кнопками-ответами "
                 "(«Сейчас посмотрю», «43-й есть», «разобрали»…). Ответ уходит в чат Авито только по твоему нажатию.\n\n"
                 f"Сейчас ждут ответа: {n} — напиши «чаты» или нажми «💬 Чаты» в меню."})
    save(st)
    return sent


def show_waiting(conn, chat_id: int) -> None:
    """Все чаты за 3 дня, где последнее слово за покупателем, — карточками (сначала свежие)."""
    try:
        chats = fetch_chats(100)
    except (requests.RequestException, SystemExit, KeyError, ValueError) as exc:
        bot.call("sendMessage", {"chat_id": chat_id, "text": f"Авито не ответило ({type(exc).__name__}) — попробуй через минуту."})
        return
    now = time.time()
    todo = [c for c in chats if waiting(c) and now - (c.get("last_message") or {}).get("created", 0) < WAIT_DAYS * 86400]
    if not todo:
        bot.call("sendMessage", {"chat_id": chat_id, "text": "💬 Все покупатели получили ответ 👌"})
        return
    bot.call("sendMessage", {"chat_id": chat_id, "text": f"💬 Ждут ответа: {len(todo)}"
                             + (f" — показываю {SHOW_MAX} самых свежих" if len(todo) > SHOW_MAX else "")})
    st = load()
    for c in todo[:SHOW_MAX]:
        try:
            if make_card(conn, st, c):
                st["seen"][c["id"]] = (c.get("last_message") or {}).get("id")
        except requests.RequestException:
            continue
    save(st)


# ---------- кнопки ----------

def refresh(card: dict, k: str) -> None:
    bot.call("editMessageText", {"chat_id": bot.owner_chat_id(), "message_id": card["msg"], "text": render_text(card),
                                 "parse_mode": "HTML", "reply_markup": kb(buttons(k, card)), "disable_web_page_preview": "true"})


def deliver(st: dict, k: str, text: str) -> str:
    card = st["cards"][k]
    err = send(card["chat"], text)
    if err:
        return f"Не ушло: {err}"
    card["sent"].append(text)
    card["greeted"] = True
    save(st)
    refresh(card, k)
    return "✅ Отправлено в Авито"


def handle(conn, cq: dict, chat_id: int, msg_id: int, data: str) -> None:
    _, what, k, *rest = data.split(":")
    st = load()
    card = st["cards"].get(k)
    note = ""
    if not card:
        note = "Карточка устарела — напиши «чаты»"
    elif what == "tpl":  # список шаблонов на месте кнопок
        items = reply_templates.load()
        btns = [b(t["title"], f"ac:t:{k}:{i}") for i, t in enumerate(items)]
        rows = [btns[j:j + 2] for j in range(0, len(btns), 2)] + [[b("↩️ Назад", f"ac:back:{k}")]]
        bot.call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": msg_id, "reply_markup": kb(rows)})
    elif what == "back":
        refresh(card, k)
    elif what == "own":
        AWAIT.write_text(json.dumps({"k": k, "until": (datetime.now() + timedelta(minutes=15)).isoformat()}), encoding="utf-8")
        bot.call("sendMessage", {"chat_id": chat_id, "text": "✏️ Напиши ответ покупателю одним сообщением — уйдёт в чат "
                                                             "Авито как есть. Без ссылок и телефонов. «отмена» — не отправлять."})
    elif what == "skip":
        card["sent"].append("⏭ без ответа")
        save(st)
        bot.call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": render_text(card),
                                     "parse_mode": "HTML", "reply_markup": kb([links(card)])})
        note = "Ок, без ответа"
    else:
        text = compose(what, card, rest[0] if rest else None)
        note = deliver(st, k, text) if text else "Нет такого шаблона — открой «💬 Шаблоны»"
    ans = {"callback_query_id": cq["id"], "text": note[:190]}
    if note.startswith("Не ушло"):
        ans["show_alert"] = "true"
    bot.call("answerCallbackQuery", ans)


def awaiting() -> dict | None:
    if not AWAIT.exists():
        return None
    a = json.loads(AWAIT.read_text(encoding="utf-8"))
    if datetime.fromisoformat(a["until"]) < datetime.now():
        AWAIT.unlink(missing_ok=True)
        return None
    return a


def handle_input(conn, chat_id: int, text: str) -> str:
    """Свой текст после «✏️ Свой текст» — сразу в чат Авито (владелец сам его написал)."""
    a = awaiting()
    AWAIT.unlink(missing_ok=True)
    if not a:
        return ""
    if text.strip().lower() in ("отмена", "cancel", "стоп"):
        return "Ок, ничего не отправил."
    st = load()
    if a["k"] not in st["cards"]:
        return "Карточка устарела — напиши «чаты»."
    return deliver(st, a["k"], text)
