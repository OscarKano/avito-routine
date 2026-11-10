"""
«📝 Дела на сегодня» — одно сообщение со всем, что ждёт владельца (просьба 25.09.2026: «открыл, сделал по списку»).
Приходит само утром (вместе с отчётом в 10:00), а ещё — кнопка в меню, команда /plan и слово «дела».

Собирает только то, где нужно действие человека: решения по сводке, заказы (черновики, без трека, едут подозрительно
долго, возвраты в пути), рассрочка, раз в неделю — жёлтые ячейки таблицы, изменения у поставщиков, пустой день в канале.
Ничего не меняет.
"""

import html
from datetime import date, datetime, timedelta

import money
import supplier_alerts
from post_format import format_title


def name(title: str | None) -> str:
    return html.escape(format_title(title or "").lstrip("• ").strip() or "—")


def build(conn, table: dict | None = None) -> tuple[str, list[str]]:
    """(текст, разделы для кнопок). table — ответ money.fetch() (если None — запросит сам)."""
    today = date.today()
    todo, sections = [], []

    # 🧺 решения по сводке рутины
    waiting = [i for (i,) in conn.execute("SELECT id FROM candidates WHERE status='new' AND digest_msg_id IS NOT NULL ORDER BY id")]
    nopr = {i for (i,) in conn.execute("SELECT id FROM candidates WHERE status='new' AND digest_msg_id IS NOT NULL AND price IS NULL")}
    if waiting:
        todo.append(f"🧺 Реши по сводке: <b>{len(waiting)}</b> ждут «Взять/Убрать» — " + ", ".join(f"№{i}" for i in waiting[:15])
                    + ("…" if len(waiting) > 15 else ""))
        if nopr:
            todo.append("   💰 Без цены (узнай у поставщика): " + ", ".join(f"№{i}" for i in sorted(nopr)))
        sections.append("routine")

    # ⭐ отзывы Авито без ответа (avito_reviews: таблица есть после первой проверки)
    try:
        no_answer = conn.execute("SELECT count(*) FROM avito_reviews WHERE state IN ('new', 'shown')").fetchone()[0]
    except Exception:
        no_answer = 0
    if no_answer:
        todo.append(f"⭐ Отзывы Авито без ответа: <b>{no_answer}</b> — ответы уже готовы, нажми «⭐ Отзывы» в меню")
        sections.append("reviews")

    # 🛒 заказы из бота
    try:
        drafts = conn.execute("SELECT id, model FROM orders WHERE state='draft' AND source<>'demo' ORDER BY id").fetchall()
        notrack = conn.execute("SELECT id, model FROM orders WHERE state='written' AND status='В процессе' AND source<>'demo' "
                               "AND (track IS NULL OR track='') ORDER BY id").fetchall()
    except Exception:
        drafts, notrack = [], []
    if drafts:
        todo.append("🛒 Внеси в таблицу (черновики): " + ", ".join(f"#{i} {html.escape(m or '—')}" for i, m in drafts))
    if notrack:
        todo.append("📮 Нет трек-номера: " + ", ".join(f"#{i} {html.escape(m or '—')}" for i, m in notrack)
                    + " — скинь скрин или номер")

    # 📒 по таблице (там и заказы, вписанные вручную)
    table = table if table is not None else money.fetch()
    if table.get("ok"):
        rows = table.get("rows") or []
        long_going = [r for r in rows if r.get("status") == "В процессе" and (d := money.parse_date(r.get("date")))
                      and (today - d).days >= 7]
        if long_going:
            todo.append("⏳ Едут 7+ дней — клиент забрал? Поменяй статус:\n" + "\n".join(
                f"   • {html.escape(r.get('date', ''))} {html.escape(r.get('model') or '—')} ({html.escape(r.get('supplier') or '?')})"
                for r in long_going[:8]))
        back = [r for r in rows if r.get("status") == "Возврат: едет назад" and (d := money.parse_date(r.get("date")))
                and (today - d).days >= 14]
        if back:
            todo.append("↩️ Возврат едет назад давно — дошёл до поставщика? Тогда «Возврат: у поставщика»:\n" + "\n".join(
                f"   • {html.escape(r.get('date', ''))} {html.escape(r.get('model') or '—')} ({html.escape(r.get('supplier') or '?')})"
                for r in back[:5]))
        bad_dates = [r for r in rows if r.get("date") and not money.parse_date(r.get("date"))]
        if bad_dates:
            todo.append("✏️ Дата с ошибкой — поправь: " + ", ".join(
                f"строка {r['row']} («{html.escape(r['date'])}», {html.escape(r.get('model') or '—')})" for r in bad_dates[:5]))
        if today.weekday() == 0:  # блок «Рассрочка» убран из таблицы 26.09 — осталась одна жёлтая ячейка
            todo.append("🟨 Понедельник: обнови в таблице «Реально в кошельке сейчас» (баланс Авито)")
        if long_going or back or bad_dates:
            sections.append("money")
    else:
        todo.append(f"⚠️ Таблица не ответила ({html.escape(str(table.get('error'))[:120])}) — заказы из неё не проверил")
    if drafts or notrack:
        sections.append("orders")

    # 📦 посылки (scripts/track_parcels.py): забрали — жди деньги и попроси отзыв; долго лежит в пункте — напомни покупателю
    try:
        since3 = (datetime.now() - timedelta(days=3)).isoformat(timespec="minutes")
        got = conn.execute("SELECT order_id, sheet_row, model FROM parcel_status WHERE event='delivered' AND event_at>=? "
                           "AND status='В процессе'", (since3,)).fetchall()
        lying = conn.execute("SELECT order_id, sheet_row, model, storage_until FROM parcel_status WHERE event='arrived' "
                             "AND event_at<=?", ((datetime.now() - timedelta(days=4)).isoformat(timespec="minutes"),)).fetchall()
    except Exception:
        got, lying = [], []
    # статус сейчас (его могли уже поменять после проверки посылки): заказ бота — из базы, вписанный вручную — из таблицы
    by_row = {r.get("row"): r.get("status") for r in (table.get("rows") or [])} if table.get("ok") else {}
    now_status = lambda oid, row: (conn.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone() or [None])[0] \
        if oid else by_row.get(row, "В процессе")
    got = [g for g in got if now_status(g[0], g[1]) == "В процессе"]
    lying = [x for x in lying if now_status(x[0], x[1]) == "В процессе"]
    who = lambda oid, row, m: (f"#{oid} " if oid else f"стр. {row} ") + html.escape(m or "—")
    if got:
        todo.append("📦 Клиент забрал — жди деньги от Авито и попроси отзыв (шаблон «Попросить отзыв»): "
                    + ", ".join(who(*g) for g in got))
    if lying:
        todo.append("📬 Лежит в пункте выдачи 4+ дня — напомни покупателю в чате Авито: " + ", ".join(
            who(o, r, m) + (f" (до {s[8:10]}.{s[5:7]})" if s else "") for o, r, m, s in lying))

    # 🏭 поставщики: изменения по выложенным моделям (scripts/watch_suppliers.py)
    alerts = supplier_alerts.recent(conn, days=3)
    if alerts:
        todo.append("🏭 У поставщиков изменения (проверь, не надо ли поправить цену или убрать):\n" + "\n".join(
            f"   • №{a['cid']} {name(a['title'])}: {html.escape(a['text'])}" for a in alerts[:8]))

    # 📅 канал сегодня
    n, first = conn.execute("SELECT count(*), min(q.slot) FROM publish_queue q JOIN candidates c ON c.id=q.candidate_id "
                            "WHERE q.slot LIKE ? AND c.status='approved'", (today.isoformat() + "%",)).fetchone()
    channel = (f"📅 Сегодня в канал: {n} моделей, первая в {first[11:16]}" if n else
               "📅 Сегодня моделей в канал нет — вчерашняя рутина не прошла или ничего не взято")
    if not n:
        todo.append(channel)

    head = f"<b>📝 Дела на {today:%d.%m}</b>"
    if not todo:
        return f"{head}\n\n✅ Дел нет — всё под контролем.\n\n{channel}", sections
    return f"{head}\n\n" + "\n\n".join(todo) + ("" if not n else f"\n\n{channel}"), sections
