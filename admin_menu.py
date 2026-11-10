"""
Главное меню админского бота (просьба пользователя 24.09.2026: «нажал — и сразу видно, что собрала рутина, какие
заказы прилетели» и т.д.). Разделы открываются на месте одного сообщения (кнопка «⬅️ Меню» возвращает назад):

  🧺 Рутина      — последний сбор: сколько прислал, сколько взял/убрал, кто ждёт решения, без цены, очередь;
                   «🔁 Запустить заново» — повторная рутина с телефона (scripts/run_routine.py);
  🛒 Заказы      — черновики и открытые заказы (нажал — пришла карточка с кнопками), новый заказ, «вывел»;
  📅 Канал       — что сегодня вышло и что ещё выйдет (модели и контентные посты), сколько на завтра;
  🤖 Бот-каталог — люди, просмотры, заявки, что чаще смотрят и что искали, а у нас нет;
  📝 Дела        — всё, что ждёт твоего действия сегодня (daily_plan.py); утром приходит само вместе с отчётом;
  💰 Деньги      — где деньги сейчас: оборот, кошелёк, в пути, у поставщиков, прибыль, рассрочка (money.py, из таблицы);
  💬 Шаблоны     — готовые ответы покупателям с кнопкой «Копировать» (reply_templates.py);
  💬 Чаты        — покупатели Авито, которые ждут ответа: карточки с кнопками-ответами (avito_chats.py);
  🕵️ Разведчик   — новые поставщики кроссовок в подписках пользователя (scripts/scout_suppliers.py, раз в неделю сам);
  🟦 Файл для ВК — товары для группы ВК файлом YML (scripts/vk_export.py): новые с прошлого раза; «вк все» — все модели;
  📈 Авито       — статистика объявлений за неделю (avito_stats.py): лидеры, «смотрят, но не пишут», фото, бренды;
  📊 Отчёт       — прислать обычный отчёт (daily_report.py) прямо сейчас;
  🩺 Проверка    — прогнать проверку системы (health_check.py) и прислать итог;
  ⭐ Отзывы      — отзывы Авито без ответа с готовыми ответами, публикация по кнопке ✅ (avito_reviews.py).
Открыть: кнопка «📋 Меню» внизу чата (постоянная), команда /menu или слово «меню».
"""

import os
import re
import sys
import json
import html
import subprocess
from datetime import date, datetime, timedelta

import config
import bot
import order_flow as of
import money
import daily_plan
import reply_templates
from post_format import format_title

ROOT = config.BASE_DIR
PYTHON = sys.executable.replace("pythonw.exe", "python.exe")
MENU_KEYBOARD = {"keyboard": [[{"text": "📋 Меню"}]], "resize_keyboard": True, "is_persistent": True}
COMMANDS = [{"command": "menu", "description": "Главное меню"}, {"command": "plan", "description": "Дела на сегодня"},
            {"command": "money", "description": "Где мои деньги"}, {"command": "templates", "description": "Шаблоны ответов"},
            {"command": "orders", "description": "Заказы"}, {"command": "report", "description": "Отчёт сейчас"},
            {"command": "avito", "description": "Статистика Авито за неделю"}, {"command": "check", "description": "Проверка системы"}]


def b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


BACK = [b("⬅️ Меню", "am:menu")]


def name(title: str | None) -> str:
    return html.escape(format_title(title or "").lstrip("• ").strip() or "—")


def hm(slot: str | None) -> str:
    return (slot or "")[11:16]


def settling(conn) -> int:
    """Взятые, но ещё без времени выхода: фото/видео качаются (schedule_queue вставляет строку со slot='' и раскладывает
    время всем в конце прогона). 30.09: меню писало «сегодня 3», пока 20 моделей ещё грузились, — выглядело как потеря."""
    return conn.execute("SELECT count(*) FROM candidates c LEFT JOIN publish_queue q ON q.candidate_id=c.id "
                        "WHERE c.status='approved' AND (q.candidate_id IS NULL OR (q.slot='' AND q.tg_done=0))").fetchone()[0]


# ---------- разделы ----------

def menu(conn) -> tuple[str, list]:
    today = date.today().isoformat()
    waiting = conn.execute("SELECT count(*) FROM candidates WHERE status='new' AND digest_msg_id IS NOT NULL").fetchone()[0]
    done, total = conn.execute("SELECT coalesce(sum(q.tg_done), 0), count(*) FROM publish_queue q JOIN candidates c "
                               "ON c.id=q.candidate_id WHERE q.slot LIKE ? AND c.status='approved'", (today + "%",)).fetchone()
    try:
        orders = conn.execute("SELECT count(*) FROM orders WHERE source<>'demo' AND (state='draft' OR (state='written' "
                              "AND status NOT IN ('Выведено', 'Возврат: отоварен')))").fetchone()[0]
    except Exception:
        orders = 0
    text = (f"<b>📋 Меню</b>\n\n🧺 Ждут твоего решения: <b>{waiting}</b>\n🛒 Открытых заказов: <b>{orders}</b>\n"
            f"📅 В канал сегодня: <b>{done} из {total}</b>\n\nВыбери раздел:")
    import avito_chats
    rows = [[b("💬 Чаты Авито", "am:chats")]] if avito_chats.ENABLED else []  # выкл. 28.10: нужна подписка с API мессенджера
    rows += [[b("📝 Дела", "am:plan"), b("💰 Деньги", "am:money"), b("💬 Шаблоны", "am:templates")],
            [b(f"🧺 Рутина · {waiting}", "am:routine"), b(f"🛒 Заказы · {orders}", "am:orders")],
            [b(f"📅 Канал · {done}/{total}", "am:channel"), b("🤖 Бот-каталог", "am:catalog")],
            [b("📈 Авито", "am:avito"), b("🕵️ Разведчик", "am:scout"), b("🟦 Файл для ВК", "am:vk")],
            [b("📊 Отчёт", "am:report"), b("🩺 Проверка", "am:health"), b("⭐ Отзывы", "am:reviews")],
            [b("🎬 Ролики", "am:videos"), b("🗂 Все модели", "am:allmodels")],
            [b("🎧 Треки", "am:tracks"), b("📱 Сторис", "am:stories")],
            [b("➕ Новый заказ", "am:neworder"), b("💸 Вывел деньги", "am:withdraw")]]
    return text, rows


def routine(conn) -> tuple[str, list]:
    last = conn.execute("SELECT max(digest_sent_at) FROM candidates WHERE digest_sent_at IS NOT NULL").fetchone()[0]
    lines = ["<b>🧺 Рутина</b>", ""]
    if last:
        day = last[:10]
        n, ok, no, wait = conn.execute(
            "SELECT count(*), sum(status='approved'), sum(status='rejected'), sum(status='new') FROM candidates "
            "WHERE substr(digest_sent_at, 1, 10)=?", (day,)).fetchone()
        lines += [f"Последний сбор: <b>{datetime.fromisoformat(last):%d.%m в %H:%M}</b> — прислал <b>{n}</b>",
                  f"✅ Взял: {ok or 0} · ❌ Убрал: {no or 0} · ⏳ Ждут решения: {wait or 0}"]
    waiting = [i for (i,) in conn.execute("SELECT id FROM candidates WHERE status='new' AND digest_msg_id IS NOT NULL ORDER BY id")]
    if waiting:
        lines.append(f"\n⏳ Всего ждут твоего решения: <b>{len(waiting)}</b> — " + ", ".join(f"№{i}" for i in waiting[:40])
                     + ("…" if len(waiting) > 40 else ""))
        lines.append("Карточки с кнопками «Взять/Убрать» — выше в этом чате (сводка рутины).")
    nopr = [i for (i,) in conn.execute("SELECT id FROM candidates WHERE status='new' AND digest_msg_id IS NOT NULL "
                                       "AND price IS NULL ORDER BY id")]
    if nopr:
        lines.append("💰 Без цены (взять нельзя, пока не узнаешь у поставщика): " + ", ".join(f"№{i}" for i in nopr))
    today, tomorrow = date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()
    ahead = dict(conn.execute("SELECT substr(q.slot, 1, 10), count(*) FROM publish_queue q JOIN candidates c "
                              "ON c.id=q.candidate_id WHERE q.tg_done=0 AND q.slot<>'' AND c.status='approved' GROUP BY 1").fetchall())
    lines.append(f"\n📦 Впереди в очереди: сегодня {ahead.get(today, 0)}, завтра {ahead.get(tomorrow, 0)}, "
                 f"всего {sum(ahead.values())}")
    loading = settling(conn)
    if loading:
        lines.append(f"⏳ Ещё встают в очередь: <b>{loading}</b> — качаются фото и видео (~1 мин на модель), время выхода "
                     "назначится в конце, бот напишет «✅ Очередь собрана»")
    lines.append("🕘 Следующий сбор — каждый день около 22:00")
    if (config.DATA_DIR / "routine_run.lock").exists():
        lines.append("🔁 Сейчас идёт повторная рутина — отчёт придёт сюда")
    else:
        lines.append("Поставщики выложили позже или сбор не пришёл — «🔁 Запустить заново»")
    return "\n".join(lines), [[b("🔁 Запустить заново", "am:rerun")], BACK]


def rerun_confirm(conn) -> tuple[str, list]:
    return ("<b>🔁 Запустить рутину заново?</b>\n\nСоберёт новые посты поставщиков (что вышло после прошлого сбора), "
            "просмотрит фото и пришлёт сводку с «Взять/Убрать», как вечером. Займёт 5–10 минут и тратит лимит Codex. "
            "ПК должен быть включён, VPN — тоже (сбор идёт через Telegram).",
            [[b("✅ Запустить", "am:rerun_go"), b("⬅️ Назад", "am:routine")]])


def orders(conn) -> tuple[str, list]:
    of.ensure(conn)
    rows = conn.execute("SELECT id, model, status, state, source, avito_sum FROM orders WHERE source<>'demo' AND "
                        "(state='draft' OR (state='written' AND status NOT IN ('Выведено', 'Возврат: отоварен'))) "
                        "ORDER BY id").fetchall()  # демо-заказы (копия таблицы) в меню не показываем
    drafts = sum(1 for r in rows if r[3] == "draft")
    going = sum(1 for r in rows if r[3] == "written" and r[2] == "В процессе")
    on_avito = [r for r in rows if r[3] == "written" and r[2] == "На Авито"]
    text = (f"<b>🛒 Заказы</b>\n\nНе внесены в таблицу (черновики): <b>{drafts}</b>\nВ пути: <b>{going}</b>\n"
            f"На Авито (ждут вывода): <b>{len(on_avito)}</b> на {of.rub(sum(r[5] or 0 for r in on_avito))}")
    text += "\n\nНажми на заказ — пришлю его карточку с кнопками:" if rows else "\n\nОткрытых заказов нет."
    btns = [[b(f"#{i} {(m or '—')[:24]} · {'черновик' if st == 'draft' else s}{' 🎬' if src == 'demo' else ''}", f"or:{i}:show")]
            for i, m, s, st, src, _ in rows]
    btns.append([b("➕ Новый заказ", "am:neworder"), b("💸 Вывел деньги", "am:withdraw")])
    return text, btns + [BACK]


def channel(conn) -> tuple[str, list]:
    today, tomorrow = date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()
    rows = conn.execute("SELECT q.slot, q.tg_done, c.title_final FROM publish_queue q JOIN candidates c ON c.id=q.candidate_id "
                        "WHERE q.slot LIKE ? AND c.status='approved' ORDER BY q.slot", (today + "%",)).fetchall()
    done = sum(r[1] for r in rows)
    lines = [f"<b>📅 Канал сегодня</b> — вышло {done} из {len(rows)}", ""]
    lines += [f"{'✅' if d else '⏳'} {hm(s)} {name(t)}" for s, d, t in rows]
    if not rows:
        waiting = conn.execute("SELECT count(*) FROM candidates WHERE status='new' AND digest_msg_id IS NOT NULL").fetchone()[0]
        lines.append("Моделей на сегодня нет." + (f" В рутине ждут решения {waiting} — нажми «Взять» у нужных, и они встанут "
                                                   "в очередь (выйдут в ближайшие часы)." if waiting else ""))
    content = conn.execute("SELECT slot, done, body FROM content_queue WHERE slot LIKE ? ORDER BY slot", (today + "%",)).fetchall()
    if content:
        lines.append("\n<b>Контентные посты</b>")
        for s, d, body in content:
            first = re.sub(r"<[^>]+>", "", (body or "").split("\n")[0])[:45]
            lines.append(f"{'✅' if d else '⏳'} {hm(s)} {html.escape(first)}")
    nxt = conn.execute("SELECT count(*), min(q.slot) FROM publish_queue q JOIN candidates c ON c.id=q.candidate_id "
                       "WHERE q.slot LIKE ? AND c.status='approved'", (tomorrow + "%",)).fetchone()
    lines.append(f"\nЗавтра: {nxt[0]} моделей" + (f", первая в {hm(nxt[1])}" if nxt[0] else ""))
    loading = settling(conn)
    if loading:
        lines.append(f"⏳ Ещё встают в очередь: {loading} — время выхода назначится, когда догрузятся все")
    return "\n".join(lines), [BACK]


def catalog(conn) -> tuple[str, list]:
    owner = bot.owner_chat_id() or 0
    now = datetime.now()
    lines = ["<b>🤖 Бот-каталог</b> (@sneakerflow_catalog_bot)", ""]
    try:
        for label, hours in (("За сутки", 24), ("За 7 дней", 24 * 7)):
            since = (now - timedelta(hours=hours)).isoformat(timespec="seconds")
            ev = dict(conn.execute("SELECT event, count(*) FROM catalog_events WHERE ts>=? AND user_id<>? GROUP BY event",
                                   (since, owner)).fetchall())
            people = conn.execute("SELECT count(DISTINCT user_id) FROM catalog_events WHERE ts>=? AND user_id<>?",
                                  (since, owner)).fetchone()[0]
            lines.append(f"{label}: людей {people}, просмотров {ev.get('view', 0)}, заявок {ev.get('order', 0)}")
        week = (now - timedelta(days=7)).isoformat(timespec="seconds")
        top = conn.execute("SELECT c.title_final, count(*) FROM catalog_events e JOIN candidates c ON c.id=e.cid WHERE "
                           "e.event='view' AND e.ts>=? AND e.user_id<>? GROUP BY e.cid ORDER BY 2 DESC LIMIT 5",
                           (week, owner)).fetchall()
        if top:
            lines.append("\n<b>Чаще смотрят (7 дней)</b>")
            lines += [f"• {name(t)} — {n}" for t, n in top]
        miss = [d for (d,) in conn.execute("SELECT DISTINCT detail FROM catalog_events WHERE event='search_miss' AND ts>=? "
                                           "AND user_id<>? ORDER BY id DESC LIMIT 10", (week, owner))]
        if miss:
            lines.append("\n<b>Искали, а у нас нет</b> (подсказка, что брать у поставщиков)")
            lines.append(", ".join(f"«{html.escape(d)}»" for d in miss))
        came = conn.execute("SELECT count(DISTINCT user_id) FROM catalog_events WHERE event='start' AND detail='channel' "
                            "AND user_id<>?", (owner,)).fetchone()[0]
        lines.append(f"\nПришли из закрепа в канале (за всё время): {came}")
    except Exception:
        lines.append("Пока нет данных.")
    try:  # «🔔 Сообщить, когда появится» — что люди ждут (подсказка, что брать у поставщиков)
        subs = [q for (q,) in conn.execute("SELECT query FROM catalog_subs WHERE active=1 AND user_id<>? ORDER BY id DESC",
                                           (owner,))]
        if subs:
            lines.append(f"\n<b>🔔 Ждут, когда появится</b> ({len(subs)}): " + ", ".join(f"«{html.escape(q)}»" for q in subs[:10]))
    except Exception:
        pass
    return "\n".join(lines), [BACK]


PLAN_BTNS = {"routine": ("🧺 Рутина", "am:routine"), "orders": ("🛒 Заказы", "am:orders"), "money": ("💰 Деньги", "am:money"),
             "reviews": ("⭐ Отзывы", "am:reviews")}


def plan(conn) -> tuple[str, list]:
    text, sections = daily_plan.build(conn)
    btns = [b(*PLAN_BTNS[s]) for s in dict.fromkeys(sections) if s in PLAN_BTNS]
    return text, ([btns] if btns else []) + [[b("🔄 Обновить", "am:plan"), b("⬅️ Меню", "am:menu")]]


def money_view(conn) -> tuple[str, list]:
    return money.view_text(money.fetch()), [[b("🔄 Обновить", "am:money"), b("⬅️ Меню", "am:menu")]]


# ---------- действия ----------

def run_script(script: str, *args: str) -> None:
    """Запустить скрипт в фоне (отчёт/проверка сами присылают результат), не задерживая кнопки бота."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    subprocess.Popen([PYTHON, str(ROOT / "scripts" / script), *args], cwd=str(ROOT), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)


def withdraw_prompt(conn, chat_id: int) -> None:
    items = of.withdraw_list(conn)
    if not items:
        bot.call("sendMessage", {"chat_id": chat_id, "text": "Заказов со статусом «На Авито» нет — выводить нечего."})
        return
    total = sum(o["avito_sum"] or 0 for o in items)
    lines = [f"💸 Перевести в «Выведено» {len(items)} заказ(ов) на {of.rub(total)}?"]
    lines += [f"• #{o['id']} {o['model']} — {of.rub(o['avito_sum'])}" + (" 🎬 демо" if o["source"] == "demo" else "") for o in items]
    lines.append("\nСверь сумму с тем, что пришло на карту.")
    bot.call("sendMessage", {"chat_id": chat_id, "text": "\n".join(lines), "reply_markup": of.kb(
        [[b("✅ Да, всё выведено", "wd:ok"), b("✖️ Нет", "wd:no")]])})


def send_menu(conn, chat_id: int) -> None:
    text, rows = menu(conn)
    bot.call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": of.kb(rows)})


def send_view(conn, chat_id: int, view) -> None:
    text, rows = view(conn)
    bot.call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": of.kb(rows)})


def setup() -> None:
    """Команды в кнопке «Меню» Telegram и постоянная кнопка «📋 Меню» внизу (ставится один раз)."""
    bot.call("setMyCommands", {"commands": json.dumps(COMMANDS, ensure_ascii=False)})
    flag = config.DATA_DIR / "admin_menu_keyboard.flag"
    if not flag.exists():
        res = bot.call("sendMessage", {"chat_id": bot.owner_chat_id(), "text": "📋 Теперь внизу всегда есть кнопка «Меню» — "
                                       "там рутина, заказы, канал, бот-каталог, отчёт и проверка.",
                                       "reply_markup": json.dumps(MENU_KEYBOARD, ensure_ascii=False)})
        if res.get("ok"):
            flag.write_text(datetime.now().isoformat(), encoding="utf-8")


VIEWS = {"menu": menu, "routine": routine, "orders": orders, "channel": channel, "catalog": catalog, "plan": plan,
         "money": money_view, "templates": reply_templates.view, "rerun": rerun_confirm}
SLOW = ("plan", "money")  # ходят в таблицу (несколько секунд) — «часики» с кнопки убираем сразу


def handle(conn, cq: dict, chat_id: int, msg_id: int, data: str) -> None:
    what = data.split(":", 1)[1]
    note = ""
    if what in SLOW:
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Смотрю таблицу…"})
    if what in VIEWS:
        text, rows = VIEWS[what](conn)
        res = bot.call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML",
                                           "reply_markup": of.kb(rows)})
        if not res.get("ok") and "not modified" not in res.get("description", ""):
            send_view(conn, chat_id, VIEWS[what])
    elif what == "rerun_go":  # повторная рутина (scripts/run_routine.py) — отчёт или причину отказа пришлёт сама
        run_script("run_routine.py")
        note = "Запустил рутину — сводка придёт через 5–10 минут"
        bot.call("editMessageText", {"chat_id": chat_id, "message_id": msg_id, "parse_mode": "HTML", "reply_markup": of.kb([BACK]),
                                     "text": f"🔁 Повторная рутина запущена в {datetime.now():%H:%M}. Сводка и отчёт придут "
                                             "сюда через 5–10 минут."})
    elif what == "chats":  # чаты Авито, где покупатель ждёт ответа (avito_chats.py)
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Смотрю чаты на Авито…"})
        import avito_chats
        avito_chats.show_waiting(conn, chat_id)
        return
    elif what == "reviews":  # отзывы Авито без ответа — пачкой с готовыми ответами (avito_reviews.py)
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Смотрю отзывы на Авито…"})
        import avito_reviews
        avito_reviews.sync(conn)
        avito_reviews.send_page(conn, chat_id)
        return
    elif what == "scout":
        run_script("scout_suppliers.py")
        note = "Смотрю каналы в твоих подписках — пришлю через 1–3 минуты"
    elif what == "vk":
        run_script("vk_export.py", "--send")
        note = "Собираю файл новых моделей для ВК — пришлю через несколько минут"
    elif what == "avito":
        run_script("avito_stats.py", "--send")
        note = "Собираю статистику Авито — пришлю примерно через минуту"
    elif what == "report":
        run_script("daily_report.py", "--no-plan")
        note = "Собираю отчёт — пришлю через ~15 секунд"
    elif what == "health":
        run_script("health_check.py", "--send")
        note = "Проверяю систему — пришлю итог через ~30 секунд"
    elif what == "videos":  # 2 ролика из свежих моделей + подписи под площадки (scripts/daily_videos.py), без публикации
        auto = (config.DATA_DIR / "autopost.on").exists()  # 11.10: новая схема — карточки в чат «Ролики» + очередь YouTube
        run_script("daily_videos.py", "--now" if auto else "--force")
        note = ("Собираю ролики (на сегодня, если ещё успеваем, иначе на завтра) — пришлю в «Ролики» через ~5–8 минут"
                if auto else "Собираю 2 ролика из свежих моделей — пришлю через 1–2 минуты")
    elif what == "allmodels":  # весь каталог за ~15 с (daily_videos.py --all-models)
        run_script("daily_videos.py", "--all-models")
        note = "Собираю «Все модели» — пришлю через ~2 минуты"
    elif what == "tracks":  # звуки для роликов «под трек» (sound_tracks.py)
        import sound_tracks
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
        sound_tracks.send_list(conn, chat_id)
        return
    elif what == "stories":
        run_script("daily_videos.py", "--stories")
        note = "Собираю сторис «кто мы» — пришлю через ~20 секунд"
    elif what == "neworder":
        of.set_awaiting(conn, None, None)
        of.send_card(conn, of.create(conn, "manual"))
    elif what == "withdraw":
        withdraw_prompt(conn, chat_id)
    if what not in SLOW:
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": note})
