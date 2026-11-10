"""
Сборка текста поста в Telegram по образцу пользователя:

• Premiata 483 (серые)

Размеры⬇️
41/42/43/44/45 EU
26/26.5/27.5/28/29 см

Цена — 4500 ₽

По вопросам пишите @sneakerflow_shop

Размеры берутся из поста поставщика (все, что у поставщика), стельки —
из того же поста, а если их там нет — из таблицы data/insole_table.json
(её строит scripts/build_insole_table.py по всем постам поставщиков).
"""

import re
import json

import config

# \b тут не подходит: в разметке постов цифры стоят вплотную к "_" ("__41/42__"),
# а "_" для регулярки — часть слова
SIZES_RE = re.compile(r"((?:(?<!\d)\d{2}\s*[/,]\s*)+\d{2}(?!\d))")
INSOLES_RE = re.compile(r"((?:\d{2}(?:[.,]\d)?\s*см\s*/\s*)+\d{2}(?:[.,]\d)?\s*см)")
TITLE_RANGE_RE = re.compile(r"(?<!\d)(\d{2})\s*[-–—]\s*(\d{2})(?!\d)")

COLOR_STEMS = [
    "черн", "бел", "сер", "красн", "розов", "зелен", "желт", "коричнев",
    "беж", "хаки", "фиолет", "оранжев", "голуб", "син", "кремов", "салатов",
    "золот", "серебр", "бордов", "мятн", "лилов", "пудров", "графит",
    "молочн", "горчичн", "оливков", "песочн", "бирюзов",
    "black", "white", "pink", "grey", "gray", "blue", "red", "green",
    "beige", "brown", "purple", "orange", "yellow", "khaki", "cream", "navy",
]
DESCRIPTORS = {
    "замшевые", "замша", "кожаные", "тройные", "треккинговые", "высокие",
    "низкие", "термо", "женские", "светлые", "тёмные", "темные", "камуфляж",
}
NOISE = {
    "кроссовки", "ботинки", "кеды", "новые", "новый", "размер", "размеры",
    "мужские", "мужская", "мужской", "зимние", "летние", "демисезонные",
    "весенние", "осенние", "осень", "зима", "лето", "весна", "—", "–", "-",
}
QUALIFIERS = {"deep", "light", "dark"}
TYPE_WORDS = {"кроссовки": "Кроссовки", "ботинки": "Ботинки", "кеды": "Кеды"}

_insole_table: dict | None = None


def _table() -> dict:
    global _insole_table
    if _insole_table is None:
        path = config.DATA_DIR / "insole_table.json"
        _insole_table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _insole_table


def _user_table() -> dict:
    """Таблица "размер -> стелька" от самого продавца (его описания на
    Avito) — приоритетнее любых данных из постов поставщиков."""
    path = config.DATA_DIR / "insole_user_table.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _is_color(token: str) -> bool:
    t = token.lower().replace("ё", "е")
    return any(stem in t for stem in COLOR_STEMS)


def format_title(avito_title: str) -> str:
    s = avito_title or ""
    s = TITLE_RANGE_RE.sub(" ", s)
    s = re.sub(r"[,]", " ", s)
    tokens = [t for t in s.split() if t.lower() not in NOISE]

    # "Женские Nike ..." в начале — переносим в конец, к цвету
    leading_gender = ""
    if tokens and tokens[0].lower() == "женские":
        leading_gender = tokens.pop(0)

    # без бренда («Ботинки чёрные женские зимние на меху»): после чистки в начале остаётся цвет, и в канал выходило
    # «• чёрные (женские на меху)» (30.09) — возвращаем вид обуви: «• Ботинки (чёрные женские на меху)»
    kind = next((TYPE_WORDS[t.lower()] for t in s.split() if t.lower() in TYPE_WORDS), None)
    if kind and tokens and (_is_color(tokens[0]) or tokens[0].lower() in DESCRIPTORS):
        tokens.insert(0, kind)

    # одиночный размер в конце ("... женские 38") — убираем
    if len(tokens) >= 2 and re.fullmatch(r"\d{2}", tokens[-1]) and 34 <= int(tokens[-1]) <= 47:
        prev = tokens[-2].lower()
        if _is_color(prev) or prev in DESCRIPTORS:
            tokens = tokens[:-1]

    split_at = None
    for i, t in enumerate(tokens):
        if i > 0 and (_is_color(t) or t.lower() in DESCRIPTORS):
            split_at = i
            break
    if split_at is None:
        model = " ".join(tokens)
        return f"• {model} ({leading_gender})" if leading_gender else f"• {model}"

    if tokens[split_at - 1].lower() in QUALIFIERS and split_at - 1 > 0:
        split_at -= 1

    model = " ".join(tokens[:split_at])
    extra = " ".join(tokens[split_at:] + ([leading_gender] if leading_gender else []))
    return f"• {model} ({extra})"


PAIRS_RE = re.compile(r"(?<!\d)(\d{2})\s*-\s*\d{2}(?:[.,]\d)?\s*-?\s*см")  # "37-23,5 см", "40-25-см"
# «Кроссовки Люкс» (31.10): построчно «✅36,22,5cm / ✅37,23.5сm.» — размер, запятая, стелька; «см» и кириллицей,
# и латиницей, и вперемешку («сm»)
COMMA_PAIRS_RE = re.compile(r"(?<!\d)(\d{2})\s*,\s*(\d{2})(?:[.,]\d)?\s*[сc][мm]", re.IGNORECASE)
RANGE_RE = re.compile(r"(?<!\d)(\d{2})\s*(?:[-–]|по|до)\s*(\d{2})(?!\d)", re.IGNORECASE)  # «41-45», «41 по 45», «с 36 до 41»


def _sizes_in_chunk(chunk: str) -> list[int]:
    """Размеры сразу после слова "Размеры": список через "/" или ","
    (41/42/43), пары "37-23,5 см / 38-24 см" или диапазон "41-45 EU"."""
    comma = [int(s) for s, ins in COMMA_PAIRS_RE.findall(chunk) if 30 <= int(s) <= 50 and 20 <= int(ins) <= 32]
    if len(comma) >= 3:  # «36,22,5cm / 37,23.5сm» — иначе SIZES_RE прочтёт «36,22» как два размера
        return comma
    run = SIZES_RE.search(chunk)
    if run:
        return [int(s) for s in re.findall(r"\d{2}", run.group(1))]
    pairs = PAIRS_RE.findall(chunk)
    if len(pairs) >= 3:
        return [int(p) for p in pairs]
    m = RANGE_RE.search(chunk[:60])
    if m and int(m.group(1)) <= int(m.group(2)):
        return list(range(int(m.group(1)), int(m.group(2)) + 1))
    return []


def parse_sizes(text: str) -> list[int]:
    sizes: list[int] = []
    for m in re.finditer(r"разме\w*", text or "", re.IGNORECASE):
        for v in _sizes_in_chunk(text[m.end(): m.end() + 250]):
            if 30 <= v <= 50 and v not in sizes:
                sizes.append(v)
    if not sizes:
        run = SIZES_RE.search(text or "")
        if run:
            sizes = [int(s) for s in re.findall(r"\d{2}", run.group(1)) if 30 <= int(s) <= 50]
    sizes = sorted(set(sizes))
    if len(sizes) == 2 and 2 <= sizes[1] - sizes[0] <= 8:  # "41/46" у поставщика — это ряд 41–46, а не два размера
        sizes = list(range(sizes[0], sizes[1] + 1))
    return sizes


def sizes_from_title(title: str) -> list[int]:
    m = TITLE_RANGE_RE.search(title or "")
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 30 <= a <= b <= 50:
            return list(range(a, b + 1))
    m = re.search(r"(?<!\d)(3\d|4[0-7])(?!\d)\s*$", title or "")
    return [int(m.group(1))] if m else []


def post_insole_map(text: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for ins in INSOLES_RE.finditer(text or ""):
        vals = [v.replace(",", ".") for v in re.findall(r"\d{2}(?:[.,]\d)?", ins.group(1))]
        runs = SIZES_RE.findall(text[: ins.start()])
        if not runs:
            continue
        sz = [int(s) for s in re.findall(r"\d{2}", runs[-1])]
        if len(sz) == len(vals):
            result.update(zip(sz, vals))
    return result


CATALOG_LINE = "Весь каталог — @sneakerflow_catalog_bot"


def build_post(avito_title: str, price, supplier_text: str, with_catalog: bool = True) -> tuple[str, list[str]]:
    """Возвращает (текст поста, список замечаний, требующих внимания).
    with_catalog=False — без строки про бот-каталог (когда пост показывает сам бот-каталог)."""
    notes: list[str] = []
    # поставщики шпигуют текст markdown-разметкой прямо посреди списков
    # размеров ("44,**__ 45") — убираем её перед разбором
    supplier_text = re.sub(r"[*_`~]+", " ", supplier_text or "")

    sizes = parse_sizes(supplier_text)
    if not sizes:
        sizes = sizes_from_title(avito_title)
        if sizes:
            notes.append("Размеры не нашлись в посте поставщика — взяты из названия Avito, проверь.")

    if not sizes:
        sizes_line = "❗️ЗАПОЛНИ ВРУЧНУЮ — не удалось распознать размеры"
        insoles_line = None
        notes.append("Размеры не распознаны.")
    else:
        sizes_line = "/".join(str(s) for s in sizes) + " EU"
        own = post_insole_map(supplier_text)
        table = _table()
        user_table = _user_table()
        signature = "/".join(str(s) for s in sizes)

        if all(str(s) in user_table for s in sizes):
            insoles_line = "/".join(user_table[str(s)] for s in sizes) + " см"
        elif all(s in own for s in sizes):
            insoles_line = "/".join(own[s] for s in sizes) + " см"
        elif signature in table.get("runs", {}):
            insoles_line = table["runs"][signature] + " см"
        else:
            per_size = table.get("per_size", {})
            values = [per_size.get(str(s)) for s in sizes]
            if all(values):
                insoles_line = "/".join(values) + " см"
                notes.append("Такого ряда размеров нет в данных поставщиков — стельки подобраны по общей таблице, проверь.")
            else:
                insoles_line = None
                notes.append("Не для всех размеров удалось определить длину стельки.")

    import html
    title_html = f"<b>{html.escape(format_title(avito_title))}</b>"
    lines = [title_html, "", "<i>Размеры⬇️</i>", sizes_line]
    if insoles_line:
        lines.append(insoles_line)
    lines += ["", f"<b>Цена — {price} ₽</b>", "", "По вопросам пишите @sneakerflow_shop"]
    if with_catalog:
        lines.append(CATALOG_LINE)
    return "\n".join(lines) + "\n", notes
