"""Изменения у поставщиков по уже выложенным моделям (пишет scripts/watch_suppliers.py, читают бот и «Дела на сегодня»).
Одно и то же изменение записывается один раз (UNIQUE cid+kind+detail) — повторно не шлётся."""

from datetime import datetime, timedelta

KIND_TEXT = {"price": "цена у поставщика {detail}", "soldout": "похоже, закончились («{detail}» в посте)",
             "sizes": "размеры теперь: {detail}", "deleted": "поставщик удалил пост — модели может уже не быть",
             "repost": "перевыложил по новой цене: {detail}"}
MIN_LEFT = 400  # кнопка «Поднять цену» — если с продажи остаётся меньше (обычная прибыль 550; −17 ₽ не повод дорожать)


def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS supplier_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cid INTEGER, kind TEXT, detail TEXT, created_at TEXT, sent INTEGER DEFAULT 0,
        UNIQUE (cid, kind, detail))""")


def add(conn, cid: int, kind: str, detail: str) -> bool:
    """True — новое изменение (записано), False — такое уже было."""
    ensure(conn)
    cur = conn.execute("INSERT OR IGNORE INTO supplier_alerts (cid, kind, detail, created_at) VALUES (?, ?, ?, ?)",
                       (cid, kind, detail, datetime.now().isoformat(timespec="seconds")))
    return cur.rowcount > 0


def text(kind: str, detail: str) -> str:
    return KIND_TEXT.get(kind, kind + ": {detail}").format(detail=detail)


def buttons(conn, cid: int, kind: str, detail: str) -> tuple[str, list] | None:
    """07.11 (владелец: слежка «херово работает» — сообщения были, а дальше ничего не менялось): по изменениям, где
    есть что делать, — пояснение и ряд кнопок. Цена у поставщика выросла и с цены на Авито остаётся меньше обычной
    прибыли -> «Поднять до X»; пост удалён / «закончились» -> «Снять с Авито». Иначе None (просто к сведению)."""
    import re
    import pricing
    row = conn.execute("SELECT price FROM publish_queue WHERE candidate_id=?", (cid,)).fetchone()
    sale = row[0] if row else None
    if kind in ("price", "repost"):
        m = re.match(r"(\d+) → (\d+)", detail)
        if not (m and sale) or int(m.group(2)) <= int(m.group(1)):
            return None
        cost = int(m.group(2))
        left = pricing.net_profit(cost, sale)
        if left >= MIN_LEFT:
            return None
        up = max(sale, pricing.avito_price(cost))
        return (f"на Авито {sale} ₽ — с новой закупки останется {left} ₽" + (" (в минус!)" if left < 0 else ""),
                [{"text": f"⬆️ №{cid}: поднять до {up} ₽", "callback_data": f"sp:up:{cid}:{up}:{cost}"},
                 {"text": "✅ Оставить", "callback_data": f"sp:keep:{cid}"}])
    if kind in ("deleted", "soldout") and sale is not None:
        return ("", [{"text": f"⛔ №{cid}: снять с Авито", "callback_data": f"sp:off:{cid}"},
                     {"text": "✅ Оставить", "callback_data": f"sp:keep:{cid}"}])
    return None


def handle(conn, cq: dict, chat_id: int, msg_id: int, data: str) -> None:
    """Кнопки под «Изменения у поставщиков»: sp:up:<cid>:<цена>:<закупка> / sp:off:<cid> / sp:keep:<cid>.
    Нажатый ряд убирается, внизу сообщения — что сделано; файл Авито пересобирается в фоне (как «Снять» у Никиты)."""
    import json
    import bot
    import nikita_stock
    parts = data.split(":")
    act, cid = parts[1], int(parts[2])
    if act == "up":
        price, cost = int(parts[3]), int(parts[4])
        conn.execute("UPDATE publish_queue SET price=? WHERE candidate_id=?", (price, cid))
        conn.execute("UPDATE candidates SET price=? WHERE id=?", (cost, cid))  # закупка теперь новая (заказы, слежка)
        conn.commit()
        note = f"⬆️ №{cid}: цена на Авито теперь {price} ₽ (закупка {cost} ₽). В канале старый пост — с прежней ценой."
    elif act == "off":
        conn.execute("UPDATE publish_queue SET avito_eligible=0 WHERE candidate_id=?", (cid,))
        conn.commit()
        note = f"⛔ №{cid}: снял с Авито."
    else:
        note = f"✅ №{cid}: оставил как есть."
    bot.call("answerCallbackQuery", {"callback_query_id": cq["id"],
                                     "text": "Секунду, обновляю файл…" if act in ("up", "off") else "Записал"})
    msg = cq.get("message", {})
    rows = [r for r in (msg.get("reply_markup") or {}).get("inline_keyboard", [])
            if not any(b.get("callback_data", "").split(":")[2:3] == [str(cid)] for b in r)]
    bot.call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": f"{msg.get('text', '')}\n{note}"[:4096],
                                 "reply_markup": json.dumps({"inline_keyboard": rows})})
    if act in ("up", "off"):
        nikita_stock._feed_dirty = True
        nikita_stock.feed_tick()


def recent(conn, days: int = 3) -> list[dict]:
    ensure(conn)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute("SELECT a.id, a.cid, a.kind, a.detail, c.title_final FROM supplier_alerts a "
                        "LEFT JOIN candidates c ON c.id=a.cid WHERE a.created_at>=? AND coalesce(c.status, '')<>'removed' "
                        "ORDER BY a.id", (since,)).fetchall()
    return [{"id": i, "cid": cid, "title": t, "text": text(k, d)} for i, cid, k, d, t in rows]
