"""
«💰 Где мои деньги» — сводка из Google-таблицы пользователя (только чтение, действие summary скрипта таблицы, версия 6+).

Цифры НЕ пересчитываются ботом: берутся готовыми из блоков сверху листа «Расчёт» («ГДЕ ДЕНЬГИ СЕЙЧАС», «ДЕНЬГИ В ПУТИ»,
«ПРИБЫЛЬ ПО ЗАКРЫТЫМ СДЕЛКАМ», «РАССРОЧКА», «ПОСТАВЩИКИ»), как они показаны на листе, по подписям — так в боте всегда
то же, что в таблице. Сам бот считает только «за этот месяц» по строкам заказов (колонка «Прибыль»).
"""

import re
import html
from datetime import date, datetime

import sheet

VALUE_RE = re.compile(r"^(?:[-−—]|[-−]?\d[\d\s .,]*\s*(?:₽|%|шт)?|\d{2}\.\d{2}\.\d{4})$")
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).lower().replace("ё", "е").replace(" ", " ")).strip()


def fetch() -> dict:
    """{"ok": True, "top": [[...]], "rows": [{...}], "today": "yyyy-mm-dd"} или {"ok": False, "error": ...}."""
    res = sheet.call("summary")
    if not res.get("ok") and "неизвестное действие" in str(res.get("error", "")):
        res["error"] = ("в таблице старая версия скрипта — обнови код скрипта (sheet_script.gs, версия 6) и сделай "
                        "«Управление развертываниями → ✏️ → Новая версия»")
    return res


def labels(top: list) -> dict:
    """Подпись -> значение справа от неё (подписи в блоках объединены на несколько ячеек, значение — через пустые)."""
    out = {}
    for row in top:
        cells = [str(c).strip() for c in row]
        i = 0
        while i < len(cells):
            c = cells[i]
            if c and not VALUE_RE.match(c):
                j = i + 1
                while j < len(cells) and not cells[j] and j - i <= 6:
                    j += 1
                if j < len(cells) and cells[j] and VALUE_RE.match(cells[j]):
                    out.setdefault(norm(c), cells[j])
                    i = j + 1
                    continue
            i += 1
    return out


def suppliers(top: list) -> list[dict]:
    """Блок «Поставщики»: имя, заказов, возвратов, доля, лежит у него, прибыль."""
    for r, row in enumerate(top):
        cells = [norm(c) for c in row]
        if "поставщик" in cells and any(c.startswith("лежит") for c in cells):
            c0 = cells.index("поставщик")  # колонки ищем только правее: слева в той же строке «ЛЕЖИТ У ПОСТАВЩИКОВ»
            cols = {k: next((i for i in range(c0 + 1, len(cells)) if cells[i].startswith(p)), None)
                    for k, p in (("orders", "заказ"), ("returns", "возврат"), ("share", "доля"), ("frozen", "лежит"),
                                 ("profit", "прибыль"))}
            res = []
            for row2 in top[r + 1:]:
                name = str(row2[c0]).strip()
                if norm(name) == "итого" or (not name and res):
                    break
                if name:
                    res.append({"name": name, **{k: (str(row2[i]).strip() if i is not None else "") for k, i in cols.items()}})
            return res
    return []


def parse_date(s: str) -> date | None:
    s = str(s or "").strip()
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except ValueError:
        pass
    # «06.09» — в таблице это настоящая дата, просто формат ячейки без года (таблица её считает): берём этот год
    try:
        d = datetime.strptime(s, "%d.%m").date().replace(year=date.today().year)
    except ValueError:
        return None
    return d.replace(year=d.year - 1) if (d - date.today()).days > 31 else d


def get(v: dict, *names: str) -> str | None:
    for n in names:
        if norm(n) in v:
            return v[norm(n)]
    return None


def show(x: str | None) -> str:
    return "—" if x in (None, "", "-", "−", "—") else html.escape(x.replace(" ", " "))


def by_month(rows: list, last: int = 4) -> list[str]:
    """Строки «Сентябрь: заказов 25 · продано 18 · возвратов 3 · прибыль 13 978 ₽» — последние месяцы, по дате заказа."""
    months: dict[tuple, dict] = {}
    for r in rows:
        d = parse_date(r.get("date"))
        if not d:
            continue
        m = months.setdefault((d.year, d.month), {"n": 0, "sold": 0, "ret": 0, "profit": 0})
        m["n"] += 1
        st = r.get("status") or ""
        if st in ("На Авито", "Выведено"):
            m["sold"] += 1
            m["profit"] += sheet.money(r.get("profit"))
        elif st.startswith("Возврат"):
            m["ret"] += 1
    out = []
    for (y, mo), m in sorted(months.items())[-last:]:
        p = f"{m['profit']:,}".replace(",", " ")
        out.append(f"   {MONTHS[mo - 1].capitalize()}{'' if y == date.today().year else f' {y}'}: заказов {m['n']} · "
                   f"продано {m['sold']} · возвратов {m['ret']} · прибыль <b>{p} ₽</b>")
    return out


def view_text(res: dict) -> str:
    if not res.get("ok"):
        return f"<b>💰 Где мои деньги</b>\n\n⚠️ Таблица не ответила: {html.escape(str(res.get('error')))}"
    v = labels(res.get("top") or [])
    today = date.today()  # не дата таблицы: у неё часовой пояс Лос-Анджелеса (на ~10 ч позади Москвы)
    lines = ["<b>💰 Где мои деньги</b> (из твоей таблицы)", ""]
    lines.append(f"Всего в обороте: <b>{show(get(v, 'ВСЕГО В ОБОРОТЕ'))}</b>")
    lines.append(f"• В кошельке Авито: {show(get(v, 'В кошельке Авито', 'Реально в кошельке сейчас'))} "
                 "<i>(вписываешь сам раз в неделю)</i>")
    going = get(v, "Заказов едет")
    lines.append(f"• Едет к покупателям: {show(get(v, 'В товаре, который едет', 'Вложено в них'))}"
                 + (f" ({show(going)})" if going and going not in ("-", "—") else "")
                 + f" → придёт {show(get(v, 'Жду с Авито'))}")
    sup = [s for s in suppliers(res.get("top") or []) if sheet.money(s.get("frozen"))]
    lines.append(f"• Лежит у поставщиков: {show(get(v, 'Заморожено у поставщиков', 'ЛЕЖИТ У ПОСТАВЩИКОВ'))}"
                 + (" — " + ", ".join(f"{html.escape(s['name'])} {show(s['frozen'])}" for s in sup) if sup else ""))
    back = get(v, "Возвраты едут назад", "Едет назад к поставщику")
    if back and back not in ("-", "—", "−"):
        lines.append(f"• Возвраты едут назад: {show(back)}")
    lines += ["", f"📈 Заработано (закрытые сделки): <b>{show(get(v, 'ЗАРАБОТАНО (закрытые сделки)', 'ЧИСТАЯ ПРИБЫЛЬ'))}</b>",
              f"   маржа {show(get(v, 'Маржа'))} · в среднем {show(get(v, 'Средняя прибыль с пары'))} с пары · "
              f"сделок {show(get(v, 'Сделок закрыто'))}",
              f"   ещё придёт с заказов в пути: ~{show(get(v, 'Ещё придёт с заказов в пути', 'Ожидаемая прибыль'))}",
              f"   уже выведено на карту: {show(get(v, 'Уже выведено на карту', 'ВЫВЕДЕНО С ПЛОЩАДКИ'))}"]
    months = by_month(res.get("rows") or [])
    if months:
        lines += ["", "📆 <b>По месяцам</b> (по дате заказа; прибыль — по проданным):"] + months
    share = get(v, "ДОЛЯ ВОЗВРАТОВ")
    if share:
        lines.append(f"↩️ Доля возвратов: {show(share)} ({show(get(v, 'Возвратов'))}) — норма до 15%")
    # блок «Рассрочка» пользователь убрал из таблицы (26.09.2026: «по сути не нужен») — в боте его тоже нет
    return "\n".join(lines)
