"""
Чтение содержимого объявления Avito через управляемый браузер (Playwright).

Официальный API Avito не отдаёт описание/фото объявления, а обычные
запросы (requests/urllib) Avito блокирует антибот-защитой. Поэтому
открываем страницу настоящим браузером и берём готовый блок данных
schema.org (JSON-LD), который есть на каждой странице объявления —
в нём уже лежат название, описание, цена и прямые ссылки на фото
(без видео).
"""

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext

import config

# Пары вида "41 — 26 см" — в описаниях пользователя это таблица размеров
SIZE_PAIR_RE = re.compile(r"(\d{2}(?:[.,]\d)?)\s*[—\-]\s*(\d{2}(?:[.,]\d)?)\s*см")
# Диапазон вида "41-45" в названии — запасной вариант
SIZE_RANGE_RE = re.compile(r"\b(\d{2})\s*-\s*(\d{2})\b")

# Ссылка на фото в CDN Avito: .../image/1/1.<7 символов id><цифра размера><остальное>
# Цифра размера кодирует, насколько крупная версия фото: "1" — маленькое
# превью (~150px, то, что лежит в html для миниатюр), "4" — полный размер
# (~720x960). Найдено опытным путём — Avito нигде явно это не описывает.
IMG_URL_RE = re.compile(
    r"https://(\d+)\.img\.avito\.st/image/1/1\.([A-Za-z0-9_-]{7})(\d)[A-Za-z0-9_.\-]*(?:\?[^\"'\\\s]*)?"
)

# Признаки того, что Avito показал страницу блокировки/проверки, а не объявление
BLOCK_MARKERS = ("доступ ограничен", "проверка безопасности", "проблема с ip", "access denied")


class BlockedError(Exception):
    """Avito показал страницу блокировки/проверки вместо объявления."""

    def __init__(self, page_title: str):
        self.page_title = page_title
        super().__init__(f"Avito заблокировал доступ: {page_title!r}")


def open_browser_context(playwright, headless: bool = True) -> BrowserContext:
    """Открывает настоящий установленный Google Chrome (не встроенную в
    Playwright тестовую сборку "Chrome for Testing" — её многие антибот-
    системы умеют отдельно распознавать как автоматизацию) с сохранённым
    профилем (cookies), чтобы не проходить проверку antibot заново на
    каждом запуске."""
    profile_dir = config.DATA_DIR / "browser_profile"
    profile_dir.mkdir(exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(profile_dir),
        channel="chrome",
        headless=headless,
        locale="ru-RU",
        viewport={"width": 1280, "height": 900},
        # скрывает от сайта явные признаки того, что браузером управляет
        # программа (Playwright/CDP), а не человек — многие антибот-
        # системы в первую очередь смотрят именно на это
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def fetch_item_page(
    context: BrowserContext, page, url: str, debug_html_path: Path | None = None
) -> tuple[dict | None, str | None]:
    """Открывает страницу объявления (в уже существующей вкладке `page`,
    чтобы не плодить новые вкладки одну за другой — так меньше похоже на
    бота) и возвращает (JSON-LD блок Product, весь HTML страницы).
    product будет None, если разобрать не получилось. Если не получилось
    и передан debug_html_path — сохраняет туда полученный HTML для
    разбора причины.

    Если Avito показал страницу блокировки/проверки — бросает BlockedError,
    чтобы вызывающий код сразу остановился и не долбил сайт дальше (это
    только ухудшает ситуацию)."""
    try:
        page.goto(url, timeout=60000, wait_until="load")
    except Exception as exc:
        # например "interrupted by another navigation" — предыдущая
        # страница (блокировка/редирект) ещё не успела успокоиться
        if debug_html_path:
            debug_html_path.write_text(f"Ошибка перехода на страницу: {exc}", encoding="utf-8")
        return None, None

    # иногда экран блокировки сам по себе сменяется на настоящую страницу
    # объявления через несколько секунд (без капчи и без участия
    # пользователя) — ждём, пока на странице появятся данные объявления,
    # до 12 секунд, вместо того чтобы читать страницу сразу
    try:
        page.wait_for_selector('script[type="application/ld+json"]', timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    html = page.content()

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else "(без заголовка)"

    if any(marker in page_title.lower() for marker in BLOCK_MARKERS):
        if debug_html_path:
            debug_html_path.write_text(html, encoding="utf-8")
        raise BlockedError(page_title)

    script = soup.find("script", {"type": "application/ld+json"})
    product = None
    if script and script.string:
        try:
            data = json.loads(script.string)
            graph = data.get("@graph", [data])
            for node in graph:
                if node.get("@type") == "Product":
                    product = node
                    break
        except json.JSONDecodeError:
            product = None

    if product is None:
        print(f"  (заголовок открывшейся страницы: {page_title!r})")
        if debug_html_path:
            debug_html_path.write_text(html, encoding="utf-8")

    return product, html


def extract_gallery_photo_urls(html: str) -> list[str]:
    """Достаёт ссылки на фото объявления из галереи в максимальном
    доступном разрешении (не мелкие превью ~150px из <img>, а полный
    размер ~720x960), и пропускает видео (определяем по иконке play на
    миниатюре — у видео она есть, у фото нет)."""
    soup = BeautifulSoup(html, "lxml")
    gallery = soup.find(attrs={"data-marker": "item-view/main-gallery"})
    if gallery is None:
        return []

    # все ссылки на CDN-фото во всём HTML, сгруппированные по
    # (поддомен, id фото) — так можно найти полноразмерный вариант той
    # же самой миниатюры, что лежит в <img>
    by_key: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for m in IMG_URL_RE.finditer(html):
        sub, photo_id, variant = m.group(1), m.group(2), m.group(3)
        by_key.setdefault((sub, photo_id), []).append((variant, m.group(0)))

    photo_urls: list[str] = []
    for li in gallery.find_all("li"):
        if li.find(attrs={"data-icon-name": "playfilled"}):
            continue  # это видео, пропускаем
        img = li.find("img", src=True)
        if not img:
            continue
        m = IMG_URL_RE.search(img["src"])
        if not m:
            continue
        sub, photo_id = m.group(1), m.group(2)
        candidates = by_key.get((sub, photo_id), [])
        big = [full_url for variant, full_url in candidates if variant == "4"]
        photo_urls.append(big[0] if big else img["src"])

    return photo_urls


def extract_sizes(title: str, description: str) -> tuple[str, bool]:
    """Пытается вытащить размеры из описания/названия.
    Возвращает (текст_размеров, уверенно_ли_разобрали)."""
    pairs = SIZE_PAIR_RE.findall(description or "")
    if pairs:
        text = ", ".join(f"{size} ({length} см)" for size, length in pairs)
        return text, True

    match = SIZE_RANGE_RE.search(title or "")
    if match:
        return f"{match.group(1)}-{match.group(2)}", False

    return "", False


def download_photos(context: BrowserContext, image_urls: list[str], dest_dir: Path, limit: int) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for i, url in enumerate(image_urls[:limit], start=1):
        resp = context.request.get(url)
        if resp.ok:
            ext = ".jpg"
            path = dest_dir / f"{i}{ext}"
            path.write_bytes(resp.body())
            saved.append(path)
    return saved
