"""
Ответы на отзывы Авито (просьба пользователя 30.09.2026). На 44 отзыва (все 5★) не было ни одного ответа: покупатель
перед заказом читает профиль, и живые ответы продавца добавляют доверия.

Бот сам готовит короткий ответ на каждый отзыв без ответа и присылает владельцу пачкой (до 5 в сообщении):
  ✅ N — опубликовать ответ на отзыв N,  ✏️ N — написать свой текст,  ✖️ N — не отвечать;
  «✅ Опубликовать все» — все ещё не решённые в этом сообщении;  «➡️ Ещё» — следующая пачка.
Публикуется ТОЛЬКО по нажатию владельца. Низкая оценка (≤3) — черновик с извинением и приглашением в сообщения Авито,
помечен ⚠️, в «Опубликовать все» не входит (только ✅ N после прочтения).
Ссылки и контакты в ответе не пропускаем: Авито такие ответы отклоняет, а за контакты может заблокировать.

API Авито: GET /ratings/v1/reviews (offset, limit ≤ 50), POST /ratings/v1/answers {reviewId, message}
(формат сверен 30.09: на неверный reviewId — 400 validate, на несуществующий — 404).
Новые отзывы проверяет scripts/check_reviews.py (из tick.py раз в 2 часа); все остальные — слово «отзывы» или
кнопка «⭐ Отзывы» в меню.
"""

import re
import sys
import json
import html
import hashlib
from datetime import datetime, timedelta

import requests

import config
import bot

sys.path.insert(0, str(config.BASE_DIR / "scripts"))
from check_avito_items import get_access_token  # noqa: E402

API = "https://api.avito.ru/ratings/v1"
AWAIT = config.DATA_DIR / "reviews_await.json"  # ждём свой текст ответа после «✏️ N» (живёт 15 минут)
PAGE = 5

# Тексты ответов. {name} — «Виталий, » (или пусто, если имени нет), {model} — модель без цвета и размеров.
# Вариант выбирается по номеру отзыва, чтобы 44 ответа подряд не были одинаковыми.
THANKS = [
    "{Name}спасибо за отзыв! Рады, что {model} понравились 🙌 Носите с удовольствием и возвращайтесь за новыми парами!",
    "{Name}спасибо, что выбрали нас! Приятно, что всё подошло. Носите с удовольствием 👟",
    "{Name}благодарим за отзыв и за покупку! Рады, что {model} пришли как надо. Будем ждать снова 🤝",
    "{Name}спасибо за тёплые слова! Рады помочь с выбором — обращайтесь, когда захочется новую пару 🔥",
]
# отзыв с «но»: пришёл не тот цвет, размер не сел, долго ехало — отвечаем по-человечески, а не «рады, что всё отлично»
PROBLEM = ("{Name}спасибо за честный отзыв и за понимание! Жаль, что {issue} — учтём и будем внимательнее. "
           "Рады, что в итоге всё устроило, носите с удовольствием!")
# только явные жалобы: «размер совпадает», «цвет как на фото» — это похвала, их не трогаем
# плохая оценка (≤3): извиниться и позвать в сообщения Авито (не в Telegram — за увод с площадки блокируют). Черновик
# есть, но «Опубликовать все» его пропускает — только ✅ N после прочтения (пользователь 30.09: «на них тоже отвечать»)
NEGATIVE = ("{Name}здравствуйте! Нам очень жаль, что {issue}. Напишите нам, пожалуйста, в сообщения на Авито — "
            "разберёмся и предложим решение.")
ISSUES = [(r"цвет\w* друг|друго\w* цвет|не тот цвет|цвет не ", "с цветом вышла накладка"),
          (r"маломер|большемер|не подош|не сел|размер не |не тот размер", "с размером вышла накладка"),
          (r"долго (ехал|шл|жд|доставл)|задерж|опозда", "доставка затянулась"),
          (r"брак|дефект|порван|отклеил", "была проблема с парой")]
NOT_A_NAME = {"пользователь", "покупатель", "продавец", "клиент"}
CONTACTS_RE = re.compile(r"https?://|t\.me|@\w|телеграм|telegram|whats ?app|ватсап|вотсап|\bтг\b|\+?\d[\d\s()-]{8,}", re.I)


# ---------- база ----------

def ensure(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS avito_reviews (review_id INTEGER PRIMARY KEY, score INTEGER, name TEXT, "
                 "item TEXT, text TEXT, created TEXT, draft TEXT, state TEXT DEFAULT 'new', msg_id INTEGER, pos INTEGER, "
                 "answer_id INTEGER, updated TEXT, first_seen TEXT)")
    conn.commit()


def headers() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def fetch_all() -> list[dict]:
    h, out, offset = headers(), [], 0
    while True:
        r = requests.get(f"{API}/reviews", headers=h, params={"offset": offset, "limit": 50}, timeout=30)
        r.raise_for_status()
        d = r.json()
        out += d.get("reviews") or []
        offset += 50
        if offset >= (d.get("total") or 0) or not d.get("reviews"):
            return out


def first_name(sender: str | None) -> str:
    """«Виталий Рубанов» -> «Виталий». Латиница, ники, компании и «Пользователь» -> без имени."""
    w = (sender or "").split()
    if not w or not re.fullmatch(r"[А-ЯЁ][а-яё]{1,14}", w[0]) or w[0].lower() in NOT_A_NAME:
        return ""
    return w[0]


def short_model(title: str | None) -> str:
    """«Кроссовки Nike Air Max 90 Patta чёрно-серые 41-45» -> «Nike Air Max 90 Patta»."""
    t = re.sub(r"—.*$", "", title or "")
    t = re.sub(r"\b(Кроссовки|Кеды|Ботинки|мужские|женские|новые|размеры)\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d{2}(\s*[-–,]\s*\d{2}\b)+", " ", t)  # только размеры «41-45», «42,44»; «Air Max 90» остаётся
    words = [x for x in t.replace(",", " ").split() if not re.fullmatch(r"[а-яё-]+(ые|ие|ий|ый)", x.lower())]
    return " ".join(words).strip() or "кроссовки"


def make_draft(r: dict) -> str:
    name = first_name((r.get("sender") or {}).get("name"))
    model = short_model((r.get("item") or {}).get("title"))
    text = (r.get("text") or "").lower()
    issue = next((what for pat, what in ISSUES if re.search(pat, text)), None)
    if (r.get("score") or 0) <= 3:
        tpl, issue = NEGATIVE, issue or "покупка не оправдала ожиданий"
    elif issue:
        tpl = PROBLEM
    else:  # номера отзывов Авито почти все с одним остатком от деления — вариант берём по хешу номера
        tpl = THANKS[int(hashlib.md5(str(r["id"]).encode()).hexdigest(), 16) % len(THANKS)]
    out = tpl.format(Name=f"{name}, " if name else "", model=model, issue=issue or "").replace(" ,", ",").strip()
    return out[:1].upper() + out[1:]


def sync(conn) -> int:
    """Отзывы с Авито -> таблица. Возвращает, сколько появилось новых без ответа."""
    ensure(conn)
    now = datetime.now().isoformat(timespec="seconds")
    known = {i: s for i, s in conn.execute("SELECT review_id, state FROM avito_reviews")}
    # первая загрузка (старые 44): first_seen='initial' — их владелец листает сам («отзывы»), тик шлёт только новые
    seen = "initial" if not known else now
    added = 0
    for r in fetch_all():
        answered = bool(r.get("answer"))
        if r["id"] in known:
            if answered and known[r["id"]] not in ("published", "skipped"):
                conn.execute("UPDATE avito_reviews SET state='published', updated=? WHERE review_id=?", (now, r["id"]))
            continue
        state = "published" if answered else ("new" if r.get("canAnswer", True) else "skipped")
        conn.execute("INSERT INTO avito_reviews (review_id, score, name, item, text, created, draft, state, updated, first_seen) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (r["id"], r.get("score"), (r.get("sender") or {}).get("name"), (r.get("item") or {}).get("title"),
                      r.get("text"), datetime.fromtimestamp(r.get("createdAt") or 0).isoformat(timespec="seconds"),
                      make_draft(r), state, now, seen))
        added += state == "new"
    conn.commit()
    return added


def pending(conn) -> int:
    ensure(conn)
    return conn.execute("SELECT count(*) FROM avito_reviews WHERE state IN ('new', 'shown')").fetchone()[0]


# ---------- сообщение-пачка ----------

def stars(n: int | None) -> str:
    return "⭐" * (n or 0)


def render(conn, msg_id: int) -> tuple[str, list]:
    rows = conn.execute("SELECT review_id, score, name, item, text, created, draft, state, pos FROM avito_reviews "
                        "WHERE msg_id=? ORDER BY pos", (msg_id,)).fetchall()
    left = conn.execute("SELECT count(*) FROM avito_reviews WHERE state IN ('new', 'shown') AND coalesce(msg_id, 0)<>?",
                        (msg_id,)).fetchone()[0]
    mark = {"published": "✅ опубликован", "skipped": "✖️ без ответа", "sending": "⏳ публикую…"}
    lines = ["<b>💬 Отзывы на Авито без ответа</b>", ""]
    btns, open_, ready = [], 0, 0
    for rid, score, name, item, text, created, draft, state, pos in rows:
        lines.append(f"<b>{pos}.</b> {stars(score)} {html.escape(name or '—')} · {created[8:10]}.{created[5:7]} · "
                     f"{html.escape(short_model(item))}")
        lines.append(f"«{html.escape((text or '').strip()[:300])}»")
        bad = (score or 0) <= 3
        if state in mark:
            lines.append(mark[state])
        elif draft:
            lines.append(("⚠️ <b>Плохой отзыв</b> — прочитай ответ, при нужде поправь (✏️), потом ✅\n" if bad else "")
                         + f"↳ <i>{html.escape(draft)}</i>")
        else:
            lines.append("↳ нет текста — напиши ответ сам (✏️)")
        lines.append("")
        if state == "shown":
            open_ += 1
            ready += bool(draft) and not bad
            btns.append([bot_b(f"✅ {pos}", f"rv:ok:{rid}") if draft else bot_b(f"— {pos}", "rv:noop"),
                         bot_b(f"✏️ {pos}", f"rv:ed:{rid}"), bot_b(f"✖️ {pos}", f"rv:sk:{rid}")])
    if ready > 1:
        btns.append([bot_b(f"✅ Опубликовать все готовые ({ready})", "rv:all")])
    if left:
        btns.append([bot_b(f"➡️ Ещё отзывы ({left})", "rv:next")])
    if not open_:
        lines.append("Готово с этой пачкой." + ("" if left else " Все отзывы с ответом 👌"))
    else:
        lines.append("✅ N — опубликовать ответ · ✏️ N — свой текст · ✖️ N — не отвечать")
    return "\n".join(lines).strip(), btns


def bot_b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def kb(rows: list) -> str:
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


def send_page(conn, chat_id: int, only_fresh: bool = False, exclude_msg: int = 0) -> bool:
    """Следующие до 5 отзывов без ответа — новым сообщением. only_fresh — только ещё не показанные (для тика).
    Сначала ещё не показанные, потом показанные раньше, но без решения; exclude_msg — пачка, где нажали «➡️ Ещё»
    (30.09: без этого «Ещё» снова присылало те же пять самых свежих)."""
    ensure(conn)
    where = "state='new' AND first_seen<>'initial'" if only_fresh else "state IN ('new', 'shown')"
    ids = [i for (i,) in conn.execute(f"SELECT review_id FROM avito_reviews WHERE {where} AND (msg_id IS NULL OR msg_id<>?) "
                                      "ORDER BY state='shown', created DESC LIMIT ?", (exclude_msg, PAGE))]
    if not ids:
        if not only_fresh:
            bot.call("sendMessage", {"chat_id": chat_id, "text": "💬 На все отзывы Авито уже есть ответы 👌"})
        return False
    res = bot.call("sendMessage", {"chat_id": chat_id, "text": "💬 Готовлю отзывы…"})
    if not res.get("ok"):
        return False  # Telegram не ответил (без VPN) — отзывы остаются «new», тик пришлёт позже
    msg_id = res["result"]["message_id"]
    for pos, rid in enumerate(ids, 1):
        conn.execute("UPDATE avito_reviews SET state='shown', msg_id=?, pos=? WHERE review_id=?", (msg_id, pos, rid))
    conn.commit()
    refresh(conn, chat_id, msg_id)
    return True


def refresh(conn, chat_id: int, msg_id: int) -> None:
    text, btns = render(conn, msg_id)
    bot.call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML",
                                 "reply_markup": kb(btns)})


# ---------- публикация ----------

def publish(conn, rid: int) -> str | None:
    """Отправить ответ на Авито. None — получилось, иначе причина."""
    row = conn.execute("SELECT draft, state FROM avito_reviews WHERE review_id=?", (rid,)).fetchone()
    if not row or row[1] == "published":
        return None
    draft = (row[0] or "").strip()
    if not draft:
        return "нет текста — нажми ✏️ и напиши ответ"
    if CONTACTS_RE.search(draft):
        return "в тексте ссылка или контакт — Авито такое отклоняет, убери"
    r = requests.post(f"{API}/answers", headers=headers(), json={"reviewId": rid, "message": draft}, timeout=30)
    if not r.ok:
        return f"Авито ответил {r.status_code}: {r.text[:150]}"
    answer_id = (r.json() or {}).get("id") if r.text.strip() else None
    conn.execute("UPDATE avito_reviews SET state='published', answer_id=?, updated=? WHERE review_id=?",
                 (answer_id, datetime.now().isoformat(timespec="seconds"), rid))
    conn.commit()
    return None


def handle(conn, cq: dict, chat_id: int, msg_id: int, data: str) -> None:
    ensure(conn)
    _, what, *rest = data.split(":")
    note = ""
    if what == "noop":
        note = "Для низкой оценки — только свой текст (✏️)"
    elif what == "next":
        send_page(conn, chat_id, exclude_msg=msg_id)
    elif what == "ok":
        err = publish(conn, int(rest[0]))
        note = "✅ Ответ опубликован" if not err else f"Не вышло: {err}"
    elif what == "all":
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Публикую…"})
        ids = [i for (i,) in conn.execute("SELECT review_id FROM avito_reviews WHERE msg_id=? AND state='shown' "
                                          "AND draft IS NOT NULL AND score>3 ORDER BY pos", (msg_id,))]  # плохие — только по одному
        errs = [e for e in (publish(conn, i) for i in ids) if e]
        refresh(conn, chat_id, msg_id)
        if errs:
            bot.call("sendMessage", {"chat_id": chat_id, "text": f"Опубликовано {len(ids) - len(errs)} из {len(ids)}. "
                                                                 f"Не вышло: {errs[0]}"})
        return
    elif what == "sk":
        conn.execute("UPDATE avito_reviews SET state='skipped', updated=? WHERE review_id=?",
                     (datetime.now().isoformat(timespec="seconds"), int(rest[0])))
        conn.commit()
        note = "Ок, без ответа"
    elif what == "ed":
        rid = int(rest[0])
        row = conn.execute("SELECT pos, name FROM avito_reviews WHERE review_id=?", (rid,)).fetchone()
        AWAIT.write_text(json.dumps({"rid": rid, "msg_id": msg_id, "until": (datetime.now() + timedelta(minutes=15)).isoformat()}),
                         encoding="utf-8")
        bot.call("sendMessage", {"chat_id": chat_id, "text": f"✏️ Напиши ответ на отзыв {row[0]} ({row[1] or 'покупатель'}) "
                                                             "одним сообщением. Без ссылок и контактов. «отмена» — не менять."})
    bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": note[:190]})
    if what in ("ok", "sk"):
        refresh(conn, chat_id, msg_id)


def awaiting() -> dict | None:
    if not AWAIT.exists():
        return None
    a = json.loads(AWAIT.read_text(encoding="utf-8"))
    if datetime.fromisoformat(a["until"]) < datetime.now():
        AWAIT.unlink(missing_ok=True)
        return None
    return a


def handle_input(conn, chat_id: int, text: str) -> str:
    """Свой текст ответа после «✏️ N»: записываем как черновик, публикует владелец кнопкой ✅ в той же пачке."""
    a = awaiting()
    AWAIT.unlink(missing_ok=True)
    if not a:
        return ""
    if text.strip().lower() in ("отмена", "cancel", "стоп"):
        return "Ок, ответ не менял."
    if CONTACTS_RE.search(text):
        return "⚠️ В тексте ссылка или контакт — Авито такой ответ отклонит (а за контакты может заблокировать). Нажми ✏️ ещё раз и напиши без них."
    conn.execute("UPDATE avito_reviews SET draft=?, state='shown' WHERE review_id=?", (text.strip()[:1000], a["rid"]))
    conn.commit()
    refresh(conn, chat_id, a["msg_id"])
    return "Записал ответ. Проверь его в пачке выше и нажми ✅ с этим номером — тогда он уйдёт на Авито."
