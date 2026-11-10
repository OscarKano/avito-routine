"""
Заказы -> Google-таблица «КРОССОВКИ: ПРИБЫЛЬ И ОБОРОТ» (лист «Расчёт») через админский бот.

Заказ появляется двумя путями:
  • сам: scripts/watch_orders.py каждые 10 минут сравнивает остатки на Авито («в наличии» 25 -> 24 = кто-то заказал)
    и присылает в админский бот карточку-черновик;
  • вручную: написать админскому боту «заказ» — для продаж, которые по остаткам не видно.
Карточка по шагам спрашивает недостающее (кнопками; суммы, модель и трек можно написать сообщением), показывает строку
целиком и ТОЛЬКО после «✅ Записать» отправляет её в таблицу (sheet.py -> Apps Script). После записи сверяет, что
таблица посчитала себестоимость как ожидалось. Дальше под карточкой кнопки статусов.

Правила денег (от пользователя, 23.09.2026):
  • «Оплачено рассрочкой» (картой) = цена у поставщика + 100 ₽ за доставку;
  • если у поставщика лежит возврат (блок «Поставщики» -> «Лежит у него»), модель идёт из заморозки до этой суммы,
    сверху картой — разница (без +100: 100 ₽ за доставку при возврате не возвращаются); потраченный возврат ->
    «Возврат: отоварен»;
  • «Сумма с Авито» = «Вы получите» со страницы заказа (обычно цена − 8%; бывает ещё −90 «скидка на доставку»).
Статусы: В процессе -> На Авито (Авито начислил деньги, ставим дату прихода) -> Выведено (забрал с площадки);
возврат: Возврат: едет назад -> Возврат: у поставщика -> (потрачен на новый заказ) Возврат: отоварен.
"""

import re
import sys
import json
import html
from datetime import date, datetime
from pathlib import Path

import config
import bot
import sheet
from post_format import format_title

SERVICES = ["Яндекс", "СДЭК", "Boxberry", "Почта России", "5post", "DPD", "Авито Доставка"]
DELIVERY = 100
AVITO_FEE = 0.08
AVITO_DELIVERY_DISCOUNT = 90
_NAMES = json.loads((config.DATA_DIR / "supplier_names.json").read_text(encoding="utf-8"))
SUPPLIERS: list[str] = _NAMES["list"]
BY_CHANNEL = {int(k): v for k, v in _NAMES["by_channel"].items()}
# трек: СДЭК «103 174 99016», Яндекс «P09319317382», Почта «805 127 250 62271» — буквы в начале + цифры с пробелами
TRACK_RE = re.compile(r"(?<![\w])([A-Za-zА-Яа-я]{0,4}\d[\d \-]{6,}\d)(?![\w])")

STATUS_BUTTONS = {  # статус -> кнопки перехода (код, подпись)
    "В процессе": [("money", "✅ Деньги пришли на Авито"), ("ret", "↩️ Клиент вернул")],
    "На Авито": [("out", "💸 Вывел с площадки")],
    "Возврат: едет назад": [("retsup", "📦 Вернулся к поставщику")],
}
STATUS_BY_CODE = {"money": "На Авито", "out": "Выведено", "ret": "Возврат: едет назад", "retsup": "Возврат: у поставщика"}


# ---------- база ----------

def ensure(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, source TEXT, avito_id INTEGER, candidate_id INTEGER,
        order_date TEXT, model TEXT, sale_price INTEGER, service TEXT, track TEXT, supplier TEXT, supplier_price INTEGER,
        paid_card INTEGER, paid_frozen INTEGER, use_returns TEXT, avito_sum INTEGER, status TEXT, money_date TEXT,
        sheet_row INTEGER, state TEXT DEFAULT 'draft', msg_id INTEGER, awaiting TEXT, extra TEXT)""")
    conn.commit()


def get(conn, oid: int) -> dict | None:
    conn.row_factory = __import__("sqlite3").Row
    row = conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    conn.row_factory = None
    return dict(row) if row else None


def save(conn, oid: int, **fields) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE orders SET {sets} WHERE id=?", (*fields.values(), oid))
    conn.commit()


def extra(o: dict) -> dict:
    return json.loads(o.get("extra") or "{}")


def candidate_info(conn, cid: int) -> dict:
    row = conn.execute("SELECT c.title_final, c.channel_id, c.price, q.price FROM candidates c "
                       "LEFT JOIN publish_queue q ON q.candidate_id=c.id WHERE c.id=?", (cid,)).fetchone()
    if not row:
        return {}
    title, channel, supplier_price, sale_price = row
    return {"candidate_id": cid, "model": format_title(title).lstrip("• ").strip(), "supplier": BY_CHANNEL.get(channel),
            "supplier_price": supplier_price, "sale_price": sale_price}


def create(conn, source: str, avito_id: int | None = None, title: str | None = None, price: int | None = None) -> int:
    """Новый черновик. По номеру объявления Авито находит нашу модель (avito_stock) — тогда сразу известны
    поставщик и его цена; для старых объявлений пользователя — только название и цена с Авито."""
    info = {}
    if avito_id:
        r = conn.execute("SELECT ad_id FROM avito_stock WHERE avito_id=?", (avito_id,)).fetchone()
        m = re.match(r"sf-c(\d+)", r[0]) if r else None  # 26.10: Id перевыложенных — «sf-c123-r1»
        if m:
            info = candidate_info(conn, int(m.group(1)))
    model = info.get("model") or (format_title(title).lstrip("• ").strip() if title else None)
    cur = conn.execute(
        "INSERT INTO orders (created_at, source, avito_id, candidate_id, order_date, model, sale_price, supplier, "
        "supplier_price, status, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'В процессе', 'draft')",
        (datetime.now().isoformat(timespec="seconds"), source, avito_id, info.get("candidate_id"), date.today().isoformat(),
         model, info.get("sale_price") or price, info.get("supplier"), info.get("supplier_price")))
    conn.commit()
    return cur.lastrowid


# ---------- шаги ----------

def step(o: dict) -> str:
    if not o["model"]:
        return "model"
    if not o["supplier"]:
        return "supplier"
    if o["supplier_price"] is None:
        return "supplier_price"
    if o["paid_card"] is None:
        return "payment"
    if not o["service"]:
        return "service"
    if o["avito_sum"] is None:
        return "avito_sum"
    if o["track"] is None:
        return "track"
    return "confirm"


def rub(x) -> str:
    return f"{int(x):,}".replace(",", " ") + " ₽" if x not in (None, "") else "—"


def ddmm(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y") if iso else "—"


def payment_text(o: dict) -> str:
    if o["paid_card"] is None:
        return "—"
    parts = []
    if o["paid_frozen"]:
        parts.append(f"из заморозки {rub(o['paid_frozen'])}")
    if o["paid_card"] or not o["paid_frozen"]:
        parts.append(f"картой {rub(o['paid_card'])}")
    return " + ".join(parts)


def frozen_at(o: dict) -> tuple[int, str | None]:
    """Сколько лежит у поставщика по таблице (блок «Поставщики» -> «Лежит у него»)."""
    res = sheet.call("frozen", _demo=o["source"] == "demo")
    if not res.get("ok"):
        return 0, res.get("error")
    return sheet.money(res["frozen"].get(o["supplier"], 0)), None


def pick_returns(o: dict) -> tuple[list[dict], str | None]:
    """Какие строки «Возврат: у поставщика» этого поставщика потратить (старые первыми) на сумму из заморозки."""
    if not o["paid_frozen"]:
        return [], None
    res = sheet.call("returns", _demo=o["source"] == "demo", supplier=o["supplier"])
    if not res.get("ok"):
        return [], res.get("error")
    chosen, total = [], 0
    for r in res["returns"]:
        if total >= o["paid_frozen"]:
            break
        amount = sheet.money(r.get("frozen_out")) or sheet.money(r.get("cost"))
        chosen.append({"row": r["row"], "model": r["model"], "supplier": r["supplier"], "date": r["date"], "amount": amount})
        total += amount
    if total < o["paid_frozen"]:
        return chosen, f"в таблице возвраты у «{o['supplier']}» на {rub(total)}, а из заморозки {rub(o['paid_frozen'])}"
    return chosen, None


def card_text(o: dict, note: str = "") -> str:
    head = {"draft": "🛒 <b>Заказ #{id}</b> — черновик", "written": "🛒 <b>Заказ #{id}</b> — в таблице",
            "cancelled": "🛒 <b>Заказ #{id}</b> — отменён (в таблицу не пошёл)"}[o["state"]].format(id=o["id"])
    src = {"avito": " (нашёл на Авито по остаткам)", "manual": " (добавлен вручную)",
           "demo": " 🎬 ДЕМО — пишется в КОПИЮ «ТЕСТ заказы»"}.get(o["source"], "")
    lines = [head + (src if o["state"] == "draft" else f", строка {o['sheet_row']}" if o["state"] == "written" else ""), ""]
    lines += [
        f"Дата заказа: {ddmm(o['order_date'])}",
        f"Модель: {html.escape(o['model'] or '—')}" + (f"  (№{o['candidate_id']})" if o["candidate_id"] else ""),
        f"Цена на Авито: {rub(o['sale_price'])}",
        f"Поставщик: {html.escape(o['supplier'] or '—')}",
        f"Цена у поставщика: {rub(o['supplier_price'])}",
        f"Оплата: {payment_text(o)}",
        f"Служба: {o['service'] or '—'}",
        f"Трек: {html.escape(o['track']) if o['track'] else ('— (добавишь позже)' if o['track'] == '' else '—')}",
        f"Сумма с Авито: {rub(o['avito_sum'])}",
        f"Статус: <b>{o['status']}</b>" + (f" (деньги пришли {ddmm(o['money_date'])})" if o["money_date"] else ""),
    ]
    ret = json.loads(o["use_returns"] or "[]")
    for r in ret:
        lines.append(f"↪️ Возврат «{html.escape(r['model'])}» от {r['date']} ({rub(r['amount'])}) → «отоварен»")
    if note:
        lines += ["", note]
    return "\n".join(lines)


def kb(rows: list) -> str:
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


def b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def screen(conn, o: dict, note: str = "") -> tuple[str, list]:
    """Текст карточки + кнопки для текущего шага."""
    oid = o["id"]
    cancel = [b("✖️ Это не заказ / отмена", f"or:{oid}:cancel")]
    if o["state"] == "cancelled":
        return card_text(o, note), []
    if o["state"] == "written":
        rows = [[b(t, f"or:{oid}:st:{code}")] for code, t in STATUS_BUTTONS.get(o["status"], [])]
        if o["status"] == "В процессе" and not o["track"]:
            rows.insert(0, [b("📮 Добавить трек", f"or:{oid}:trk:edit")])
        return card_text(o, note), rows

    s = step(o)
    if s == "model":
        set_awaiting(conn, oid, "model")
        return card_text(o, note or "✍️ Напиши, какая модель (например «9060 бежевые» или название как на Авито)."), [cancel]
    if s == "supplier":
        btns = [b(n, f"or:{oid}:sup:{i}") for i, n in enumerate(SUPPLIERS)]
        return card_text(o, note or "👇 Какой поставщик?"), [btns[i:i + 3] for i in range(0, len(btns), 3)] + [cancel]
    if s == "supplier_price":
        set_awaiting(conn, oid, "supplier_price")
        return card_text(o, note or "✍️ Напиши цену у поставщика (без +100 за доставку), например 3000."), [cancel]
    if s == "payment":
        ex = extra(o)
        if "frozen" not in ex or ex.get("frozen_err"):  # спрашиваем таблицу один раз на шаге (ошибку — повторно)
            ex["frozen"], ex["frozen_err"] = frozen_at(o)
            save(conn, oid, extra=json.dumps(ex, ensure_ascii=False))
        price, frozen = o["supplier_price"], ex["frozen"]
        rows = []
        info = ""
        if frozen > 0:
            use = min(frozen, price)
            rows.append([b(f"❄️ Из заморозки {rub(use)} + картой {rub(price - use)}", f"or:{oid}:pay:frozen")])
            info = f"У «{o['supplier']}» лежит {rub(frozen)} (по таблице). "
        rows.append([b(f"💳 Всё картой: {rub(price + DELIVERY)}", f"or:{oid}:pay:card")])
        rows.append([b("✏️ Ввести вручную", f"or:{oid}:pay:edit"), b("✏️ Цена поставщика", f"or:{oid}:ed:supplier_price")])
        err = f"⚠️ Заморозку в таблице посмотреть не смог: {ex['frozen_err']}. " if ex.get("frozen_err") else ""
        return card_text(o, note or f"{err}{info}👇 Как оплатил поставщику?"), rows + [cancel]
    if s == "service":
        btns = [b(n, f"or:{oid}:svc:{i}") for i, n in enumerate(SERVICES)]
        return card_text(o, note or "👇 Какая служба доставки?"), [btns[i:i + 3] for i in range(0, len(btns), 3)] + [cancel]
    if s == "avito_sum":
        set_awaiting(conn, oid, "avito_sum")  # сумму можно и просто написать сообщением
        rows = []
        if o["sale_price"]:
            full = o["sale_price"] - round(o["sale_price"] * AVITO_FEE)
            rows.append([b(f"{rub(full)} (−8%)", f"or:{oid}:sum:{full}"),
                         b(f"{rub(full - AVITO_DELIVERY_DISCOUNT)} (−8% −90)", f"or:{oid}:sum:{full - AVITO_DELIVERY_DISCOUNT}")])
        rows.append([b("✏️ Другая сумма", f"or:{oid}:sum:edit")])
        return card_text(o, note or "👇 Сколько придёт с Авито? Сверь с «Вы получите» на странице заказа."), rows + [cancel]
    if s == "track":
        set_awaiting(conn, oid, "track")
        return card_text(o, note or "✍️ Пришли трек (можно переслать сообщение поставщика) или нажми «позже»."), \
            [[b("⏭ Трека пока нет — добавлю позже", f"or:{oid}:trk:skip")], cancel]
    # confirm
    ex = extra(o)
    if o["paid_frozen"] and ("returns_checked" not in ex or ex.get("returns_err")):
        chosen, err = pick_returns(o)
        save(conn, oid, use_returns=json.dumps(chosen, ensure_ascii=False))
        ex["returns_checked"], ex["returns_err"] = True, err
        save(conn, oid, extra=json.dumps(ex, ensure_ascii=False))
        o = get(conn, oid)
    warn = f"\n⚠️ {ex['returns_err']} — возврат отметь «отоварен» сам." if ex.get("returns_err") else ""
    text = card_text(o, note or f"Проверь строку. В таблицу уйдёт ровно это, статус «В процессе».{warn}")
    rows = [[b("✅ Записать в таблицу", f"or:{oid}:write")],
            [b("✏️ Изменить", f"or:{oid}:edit")], cancel]
    return text, rows


def edit_menu(o: dict) -> list:
    oid = o["id"]
    fields = [("model", "Модель"), ("supplier", "Поставщик"), ("supplier_price", "Цена поставщика"), ("payment", "Оплата"),
              ("service", "Служба"), ("avito_sum", "Сумма с Авито"), ("track", "Трек"), ("order_date", "Дата")]
    btns = [b(t, f"or:{oid}:ed:{f}") for f, t in fields]
    return [btns[i:i + 2] for i in range(0, len(btns), 2)] + [[b("⬅️ Назад", f"or:{oid}:back")]]


def reset(conn, o: dict, field: str) -> None:
    """Сбросить поле (и то, что от него зависит), чтобы шаг спросил его заново."""
    oid = o["id"]
    ex = extra(o)
    ex.pop("returns_checked", None)
    ex.pop("returns_err", None)
    if field in ("supplier", "supplier_price", "payment"):
        ex.pop("frozen", None)
        ex.pop("frozen_err", None)
    upd = {"extra": json.dumps(ex, ensure_ascii=False), "use_returns": None}
    if field == "supplier":
        upd.update(supplier=None, paid_card=None, paid_frozen=None)
    elif field == "supplier_price":
        upd.update(supplier_price=None, paid_card=None, paid_frozen=None)
    elif field == "payment":
        upd.update(paid_card=None, paid_frozen=None)
    elif field == "order_date":
        upd.update(awaiting="order_date")
    elif field in ("model", "service", "avito_sum", "track"):
        upd[field] = None
    save(conn, oid, **upd)


# ---------- отправка карточки ----------

def send_card(conn, oid: int, note: str = "") -> None:
    o = get(conn, oid)
    text, rows = screen(conn, o, note)
    res = bot.call("sendMessage", {"chat_id": bot.owner_chat_id(), "text": text, "parse_mode": "HTML",
                                   "reply_markup": kb(rows)})
    if res.get("ok"):
        save(conn, oid, msg_id=res["result"]["message_id"])


def refresh(conn, oid: int, note: str = "", rows: list | None = None) -> None:
    """Перерисовать карточку на месте (если не выходит — прислать заново внизу)."""
    o = get(conn, oid)
    text, default_rows = screen(conn, o, note)
    res = bot.call("editMessageText", {"chat_id": bot.owner_chat_id(), "message_id": o["msg_id"], "text": text,
                                       "parse_mode": "HTML", "reply_markup": kb(rows if rows is not None else default_rows)})
    if not res.get("ok") and "not modified" not in res.get("description", ""):
        send_card(conn, oid, note)


def set_awaiting(conn, oid: int | None, what: str | None) -> None:
    conn.execute("UPDATE orders SET awaiting=NULL WHERE awaiting IS NOT NULL")
    if oid:
        save(conn, oid, awaiting=what)
    conn.commit()


# ---------- запись в таблицу ----------

def sheet_fields(o: dict) -> dict:
    return {"date": o["order_date"], "model": o["model"], "service": o["service"], "track": o["track"] or "",
            "supplier": o["supplier"], "paid_card": o["paid_card"] or "", "paid_frozen": o["paid_frozen"] or "",
            "avito_sum": o["avito_sum"], "status": "В процессе"}


def check_row(o: dict, values: dict) -> list[str]:
    """Сверка того, что записалось и что посчитали формулы, с ожидаемым."""
    problems = []
    soft = lambda s: " ".join(str(s or "").lower().replace("ё", "е").split())  # скрипт пишет название ровно как в списке
    if values.get("model") != o["model"]:
        problems.append(f"модель в таблице «{values.get('model')}»")
    if soft(values.get("supplier")) != soft(o["supplier"]):
        problems.append(f"поставщик в таблице «{values.get('supplier')}»")
    if sheet.money(values.get("avito_sum")) != o["avito_sum"]:
        problems.append(f"сумма с Авито в таблице {values.get('avito_sum')}")
    expected_cost = (o["paid_card"] or 0) + (o["paid_frozen"] or 0)
    if "cost" in values and sheet.money(values["cost"]) != expected_cost:
        problems.append(f"себестоимость в таблице {values['cost']}, ожидал {rub(expected_cost)}")
    return problems


def write(conn, oid: int) -> str:
    o = get(conn, oid)
    if o["state"] != "draft" or step(o) != "confirm":
        return "Заказ уже записан или не заполнен"
    res = sheet.call("append", _demo=o["source"] == "demo", id=oid, fields=sheet_fields(o))
    if not res.get("ok"):
        refresh(conn, oid, f"❌ Не записал: {html.escape(res.get('error', '?'))}\nНичего не изменилось — можно нажать ещё раз.")
        return "Не получилось"
    save(conn, oid, state="written", sheet_row=res["row"], awaiting=None)
    notes = []
    if res.get("duplicate"):
        notes.append("ℹ️ Этот заказ уже был в таблице — второй раз не записывал.")
    problems = check_row(get(conn, oid), res.get("values", {}))
    for r in json.loads(o["use_returns"] or "[]"):
        rr = sheet.call("use_return", _demo=o["source"] == "demo", row=r["row"], model=r["model"], supplier=r["supplier"])
        if rr.get("ok"):  # 16.10: и в своём списке заказов (раньше менялась только таблица — заказ-возврат «висел»)
            conn.execute("UPDATE orders SET status='Возврат: отоварен' WHERE sheet_row=? AND source=?", (r["row"], o["source"]))
            conn.commit()
        notes.append(f"↪️ Возврат «{html.escape(r['model'])}» (строка {r['row']}) → отоварен" if rr.get("ok") else
                     f"⚠️ Возврат «{html.escape(r['model'])}» не отметил: {html.escape(rr.get('error', '?'))} — поставь «отоварен» сам")
    if problems:
        notes.append("⚠️ ПРОВЕРЬ СТРОКУ В ТАБЛИЦЕ: " + "; ".join(html.escape(p) for p in problems))
    else:
        notes.append(f"✅ Сверил: записалось верно, себестоимость {res['values'].get('cost', '?')}.")
    refresh(conn, oid, "\n".join(notes))
    return "Записал"


def set_status(conn, oid: int, code: str) -> str:
    o = get(conn, oid)
    new = STATUS_BY_CODE[code]
    if o["state"] != "written" or code not in dict(STATUS_BUTTONS.get(o["status"], [])):
        return "Этот статус уже не актуален"
    fields = {"status": new}
    if code == "money":
        fields["money_date"] = date.today().isoformat()
    res = sheet.call("update", _demo=o["source"] == "demo", id=oid, fields=fields)
    if not res.get("ok"):
        refresh(conn, oid, f"❌ Статус не поменял: {html.escape(res.get('error', '?'))}")
        return "Не получилось"
    save(conn, oid, status=new, money_date=fields.get("money_date", o["money_date"]))
    v = res.get("values", {})
    note = f"✅ Статус в таблице: {html.escape(v.get('status', new))}"
    if code == "money":
        expected = o["avito_sum"] - (o["paid_card"] or 0) - (o["paid_frozen"] or 0)
        got = sheet.money(v.get("profit"))
        note += f", прибыль {v.get('profit', '?')}" + ("" if got == expected else f" ⚠️ ожидал {rub(expected)} — проверь")
    refresh(conn, oid, note)
    return new


# ---------- ввод текстом ----------

def parse_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits and len(digits) <= 7 else None


_LOOKALIKE = str.maketrans("РАВЕКМНОСТХУ", "PABEKMHOCTXY")  # распознавание по-русски путает буквы в «P0931…»


def find_tracks(text: str) -> list[str]:
    """Все похожие на трек номера в тексте (или распознанном со скрина), без номеров заказа Авито и телефонов."""
    out = []
    for m in TRACK_RE.finditer(text or ""):
        t = re.sub(r"[ \-]", "", m.group(1)).upper().translate(_LOOKALIKE)
        before = (text[max(0, m.start() - 15):m.start()]).lower()
        if sum(ch.isdigit() for ch in t) < 8:
            continue
        if re.fullmatch(r"7\d{16}", t):  # номер заказа Авито: 17 цифр на 7 («70000000523068796»)
            continue
        if re.fullmatch(r"[78]9\d{9}", t) or "+" in before[-2:]:  # телефон
            continue
        if t not in out:
            out.append(t)
    return out


def find_track(text: str) -> str | None:
    tracks = find_tracks(text)
    return tracks[0] if tracks else None


def ocr(path) -> str:
    """Текст с картинки — встроенным распознаванием Windows (scripts/ocr_image.ps1), картинка никуда не уходит."""
    import subprocess
    res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(config.BASE_DIR / "scripts" / "ocr_image.ps1"), "-Path", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                         creationflags=0x08000000)
    return res.stdout or ""


def match_models(conn, text: str) -> list[dict]:
    """Наши модели (вышедшие в канал), похожие на написанное, — чтобы подставить поставщика и цену."""
    scripts = str(Path(__file__).resolve().parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import catalog_bot
    found, _, _, partial = catalog_bot.search(catalog_bot.load_models(conn), text)
    return [] if partial else found[:5]  # «похожие» тут не нужны — только точные совпадения


def handle_input(conn, o: dict, text: str) -> None:
    oid, what = o["id"], o["awaiting"]
    if what == "model":
        matches = match_models(conn, text)
        save(conn, oid, model=text.strip()[:80], awaiting=None)
        if matches:
            rows = [[b(f"№{m['id']} {m['name'][:30]} — {m['price']} ₽", f"or:{oid}:cand:{m['id']}")] for m in matches]
            rows.append([b("✍️ Нет, оставить как написал", f"or:{oid}:back")])
            refresh(conn, oid, "Это одна из наших моделей? Тогда подставлю поставщика и цену.", rows)
            return
    elif what == "supplier_price":
        v = parse_int(text)
        if not v:
            refresh(conn, oid, "Не понял сумму — напиши числом, например 3000.")
            return
        save(conn, oid, supplier_price=v, awaiting=None)
    elif what == "payment":
        nums = [int(x) for x in re.findall(r"\d+", text.replace(" ", ""))]
        if not nums or len(nums) > 2:
            refresh(conn, oid, "Не понял. Напиши «3100» (всё картой) или «600 2900» (картой, из заморозки).")
            return
        save(conn, oid, paid_card=nums[0], paid_frozen=nums[1] if len(nums) == 2 else 0, awaiting=None)
    elif what == "avito_sum":
        v = parse_int(text)
        if not v:
            refresh(conn, oid, "Не понял сумму — напиши числом, например 3671.")
            return
        save(conn, oid, avito_sum=v, awaiting=None)
    elif what == "track":
        t = find_track(text) or (text.strip().upper() if re.fullmatch(r"[\w\- ]{6,30}", text.strip()) else None)
        if not t:
            refresh(conn, oid, "Не нашёл трек в сообщении — пришли только номер.")
            return
        save(conn, oid, track=t, awaiting=None)
        if o["state"] == "written":
            res = sheet.call("update", _demo=o["source"] == "demo", id=oid, fields={"track": t})
            refresh(conn, oid, "✅ Трек записан в таблицу" if res.get("ok") else f"❌ Трек не записал: {html.escape(res.get('error', '?'))}")
            return
    elif what == "order_date":
        m = re.fullmatch(r"\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\s*", text)
        try:
            y = int(m.group(3)) if m and m.group(3) else date.today().year
            d = date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
        except (AttributeError, ValueError):
            refresh(conn, oid, "Не понял дату — напиши, например, 23.09")
            return
        save(conn, oid, order_date=d.isoformat(), awaiting=None)
    refresh(conn, oid)


# ---------- кнопки ----------

def handle_callback(conn, data: str) -> str:
    """data = "or:<id>:<действие>[:<аргумент>]". Возвращает короткий ответ для всплывашки."""
    _, oid, action, *arg = data.split(":", 3)
    oid = int(oid)
    o = get(conn, oid)
    if not o:
        return "Заказ не найден"
    a = arg[0] if arg else ""
    if action == "show":  # из списка «заказы» — прислать карточку заново внизу чата
        send_card(conn, oid)
        return ""
    if o["state"] == "cancelled" and action != "restore":
        return "Заказ отменён"
    if o["state"] == "written" and action not in ("st", "trk"):
        return "Уже в таблице"

    if action == "sup":
        save(conn, oid, supplier=SUPPLIERS[int(a)])
    elif action == "cand":
        reset(conn, o, "supplier")  # поставщик/цена/оплата — заново от выбранной модели
        info = candidate_info(conn, int(a))
        save(conn, oid, awaiting=None, **{k: v for k, v in info.items() if v is not None})
    elif action == "pay":
        ex = extra(o)
        if a == "frozen" and ex.get("frozen", 0) > 0:
            use = min(ex["frozen"], o["supplier_price"])
            save(conn, oid, paid_frozen=use, paid_card=o["supplier_price"] - use)
        elif a in ("card", "frozen"):  # «из заморозки», когда заморозки нет, — обычная оплата картой (+100)
            save(conn, oid, paid_card=o["supplier_price"] + DELIVERY, paid_frozen=0)
        elif a == "edit":
            set_awaiting(conn, oid, "payment")
            refresh(conn, oid, "✍️ Напиши, сколько заплатил: «3100» — всё картой, или «600 2900» — картой и из заморозки.")
            return "Жду сумму"
    elif action == "svc":
        save(conn, oid, service=SERVICES[int(a)])
    elif action == "sum":
        if a == "edit":
            set_awaiting(conn, oid, "avito_sum")
            refresh(conn, oid, "✍️ Напиши сумму «Вы получите» со страницы заказа на Авито.")
            return "Жду сумму"
        save(conn, oid, avito_sum=int(a))
    elif action == "trk":
        if a == "skip":
            save(conn, oid, track="", awaiting=None)
        else:
            set_awaiting(conn, oid, "track")
            refresh(conn, oid, "✍️ Пришли трек или перешли сообщение поставщика с ним.")
            return "Жду трек"
    elif action == "write":
        return write(conn, oid)
    elif action == "edit":
        refresh(conn, oid, "Что поменять?", edit_menu(o))
        return ""
    elif action == "ed":
        reset(conn, o, a)
        if a in ("model", "supplier_price", "order_date"):
            set_awaiting(conn, oid, a)
        if a == "order_date":
            refresh(conn, oid, "✍️ Напиши дату заказа, например 23.09")
            return "Жду дату"
    elif action == "back":
        pass
    elif action == "cancel":
        refresh(conn, oid, "Точно отменить? В таблицу ничего не пойдёт.",
                [[b("Да, отменить", f"or:{oid}:cancel2"), b("Нет, назад", f"or:{oid}:back")]])
        return ""
    elif action == "cancel2":
        save(conn, oid, state="cancelled", awaiting=None)
    elif action == "st":
        return set_status(conn, oid, a)
    refresh(conn, oid)
    return ""


def withdraw_list(conn) -> list[dict]:
    rows = conn.execute("SELECT id FROM orders WHERE state='written' AND status='На Авито' AND source<>'demo' "
                        "ORDER BY id").fetchall()
    return [get(conn, r[0]) for r in rows]
