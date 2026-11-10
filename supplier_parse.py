"""Разбор поста поставщика: название, цена (штучно), пол, "отпечаток" первого фото.

Всё, что можно вытащить из текста поста без "глаз". Цвет у поставщика часто
только на фото — поэтому одинаковое название у разных постов не значит повтор
(6 цветов Jordan 13 = 6 разных моделей); повтор определяем по первому фото.
"""

import re
from pathlib import Path

from PIL import Image

from post_format import parse_sizes


def clean(text: str) -> str:
    return re.sub(r"[*_`~]+", " ", text or "")


def parse_title(text: str) -> str:
    for line in clean(text).split("\n"):
        line = re.sub(r"^[^\w(]+", "", line.strip())  # ведущие тире, эмодзи, стрелки
        if not line or re.match(r"(?i)(арт|размер|цена|отпр|канал|заказ)", line):
            continue
        if re.search(r"[A-Za-zА-Яа-я]{3}", line):
            return re.sub(r"\s+", " ", line)[:80]
    return ""


def parse_price(text: str) -> int | None:
    """Цена штучно (розница). "Цена за ряд" и оптовые строки пропускаем."""
    lines = clean(text).split("\n")
    for with_currency in (True, False):  # сначала строго "2500 ₽", потом "Цена : 2500" без знака валюты
        for line in lines:
            low = line.lower()
            if "ряд" in low or ("опт" in low and "розн" not in low):
                continue
            if "цена" in low or "розниц" in low:
                pattern = r"(\d[\d ]{2,6}\d)\s*(?:₽|р\b|руб)" if with_currency else r"(?<![\d.,])(\d[\d ]{2,6}\d)(?![\d.,])"
                m = re.search(pattern, line)
                if m:
                    return int(re.sub(r"\s", "", m.group(1)))
    # слова «цена» нет — бывает, что оно картинкой-эмодзи (ст4-70: плашка «ЛУЧШАЯ ЦЕНА» в тексте = «✅✅✅✅✅:4500₽»,
    # а с 12.10 и без рубля — «✅✅✅✅✅:3300»). Тогда берём сумму со знаком рубля или сумму после двоеточия в строке
    # без единой буквы (одни эмодзи и «:»), если в посте она ОДНА (не опт/ряд) — две разные суммы не угадываем
    found = set()
    for line in lines:
        low = line.lower()
        if "ряд" in low or "опт" in low:
            continue
        hits = list(re.finditer(r"(?<![\d.,])(\d[\d ]{2,6}\d)\s*(?:₽|руб)", line))
        plate = re.fullmatch(r"[^\w]*:\s*(\d[\d ]{2,6}\d)\s*(?:₽|р|руб)?\.?", line.strip())
        for m in hits + ([plate] if plate else []):
            v = int(re.sub(r"\s", "", m.group(1)))
            if 500 <= v <= 50000:
                found.add(v)
    return found.pop() if len(found) == 1 else None


def guess_gender(channel_name: str, sizes: list[int]) -> str:
    # Правило пользователя: женские — размеры 36/37…41; мужские — 41…45/46/47. Если у поставщика широкий ряд
    # (37–45, 37–46 и т.п.) — ставим МУЖСКУЮ категорию (пишут всё равно и девушки). Цвет не учитываем.
    if sizes:
        return "female" if max(sizes) <= 41 else "male"
    return "female" if "енск" in channel_name.lower() else "male"  # размеров нет — по названию канала


def parse_post(channel_name: str, text: str) -> dict:
    sizes = parse_sizes(clean(text))
    return {
        "title": parse_title(text),
        "price": parse_price(text),
        "sizes": sizes,
        "gender": guess_gender(channel_name, sizes),
    }


def dhash(path: Path) -> int:
    img = Image.open(path).convert("L").resize((9, 8))
    px = list(img.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def fine_dhash(path: Path, n: int = 16) -> int:
    """Тот же отпечаток, но 16×16 (256 бит). 07.11: 8×8 путал РАЗНЫЕ модели одной съёмки поставщика (тот же фон,
    ракурс, чёрная пара): AF1 Mid ~ Timberland, NB 574 ~ NB 9060, Pegasus ~ Jordan 4. Настоящие повторы — 0–2 бита,
    ложные — 43–72 (66 повторов за 6 недель)."""
    img = Image.open(path).convert("L").resize((n + 1, n))
    px = list(img.getdata())
    bits = 0
    for row in range(n):
        for col in range(n):
            bits = (bits << 1) | (px[row * (n + 1) + col] > px[row * (n + 1) + col + 1])
    return bits


def csig(path: Path) -> str:
    """Грубая цветовая подпись фото (сетка 4x4, RGB) — чтобы разные цвета одной модели,
    снятые с того же ракурса, не приняли за одно и то же фото."""
    img = Image.open(path).convert("RGB").resize((4, 4))
    return ",".join(f"{v:02x}" for px in img.getdata() for v in px)


def csig_distance(a: str, b: str) -> float:
    va = [int(x, 16) for x in a.split(",")]
    vb = [int(x, 16) for x in b.split(",")]
    return sum(abs(x - y) for x, y in zip(va, vb)) / len(va)
