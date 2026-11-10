"""Загрузка настроек из файла .env. Ничего здесь не редактируй руками —
свои значения меняй в .env."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

AVITO_CLIENT_ID = os.getenv("AVITO_CLIENT_ID", "")
AVITO_CLIENT_SECRET = os.getenv("AVITO_CLIENT_SECRET", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
CATALOG_BOT_TOKEN = os.getenv("CATALOG_BOT_TOKEN", "")  # отдельный публичный бот-каталог для покупателей (не админский)
# адрес мини-витрины (scripts/build_showcase.py -> бесплатный хостинг); пока пусто — кнопки витрины в боте нет
SHOWCASE_URL = os.getenv("SHOWCASE_URL", "https://oscarkano.github.io/shop/")
# ссылка на канал для подписей к роликам и шапок профилей (канал закрытый — пригласительная ссылка; станет публичным —
# заменить на https://t.me/<адрес> в .env)
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/+X7_wMKzWrNZlY2E6")
# пригласительная ссылка из шапки ТикТока (поставил владелец; до 09.10 стояла и в инсте)
CHANNEL_LINK_SOCIAL = os.getenv("CHANNEL_LINK_SOCIAL", "https://t.me/+b4rE67ahgk1mZDUy")
# с 09.10.2026 у инсты и ВК свои ссылки — Telegram считает входы по каждой (scripts/channel_sources.py). Инста: шапка и
# страница-переход <витрина>/tg/ для стикеров в сторис (стикеры с t.me инста делает некликабельными, 07.10.2026)
CHANNEL_LINK_INSTAGRAM = os.getenv("CHANNEL_LINK_INSTAGRAM", "https://t.me/+vskwZsKHx3M1NTg6")
CHANNEL_LINK_VK = os.getenv("CHANNEL_LINK_VK", "https://t.me/+LWMC5QUGvE0xZjcy")
# git-адрес репозитория GitHub Pages для витрины (scripts/publish_showcase.py); аккаунт пользователя, создан 06.10.2026
SHOWCASE_REPO = os.getenv("SHOWCASE_REPO", "https://github.com/OscarKano/shop.git")
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# Сколько фото брать из объявления (первые N, без видео)
PHOTOS_PER_POST = int(os.getenv("PHOTOS_PER_POST", "8"))

# Цена: чистая прибыль после комиссии Авито и скидки на доставку.
# PRICE_MIN — нижняя граница цены; цена всегда округляется вверх до ...90.
PRICE_TARGET_PROFIT = int(os.getenv("PRICE_TARGET_PROFIT", "550"))
PRICE_AVITO_FEE = float(os.getenv("PRICE_AVITO_FEE", "0.08"))
PRICE_DELIVERY_SUBSIDY = int(os.getenv("PRICE_DELIVERY_SUBSIDY", "90"))
PRICE_MIN = int(os.getenv("PRICE_MIN", "3990"))

YANDEX_DISK_TOKEN = os.getenv("YANDEX_DISK_TOKEN", "")

# Google-таблица заказов: адрес веб-приложения Apps Script (код — sheet_script.gs) и общий с ним секрет
SHEET_WEBAPP_URL = os.getenv("SHEET_WEBAPP_URL", "")
SHEET_SECRET = os.getenv("SHEET_SECRET", "")
SHEET_DEMO_URL = os.getenv("SHEET_DEMO_URL", "")  # копия таблицы «ТЕСТ заказы» — только для демо-заказов (source='demo')

# Окно, в котором в течение дня выходят новые объявления (Авито и Telegram-канал), часы по Москве
PUBLISH_START_HOUR = int(os.getenv("PUBLISH_START_HOUR", "9"))
PUBLISH_END_HOUR = int(os.getenv("PUBLISH_END_HOUR", "21"))

# Сколько штук "в наличии" ставить на каждом объявлении Авито (пользователь всегда ставит 25)
STOCK_QUANTITY = int(os.getenv("STOCK_QUANTITY", "25"))

# Через сколько дней повтор той же модели можно выложить заново (с другим первым фото)
REPEAT_AFTER_DAYS = int(os.getenv("REPEAT_AFTER_DAYS", "12"))

LOGS_DIR = BASE_DIR / "logs"
PREVIEW_DIR = BASE_DIR / "preview"
PHOTOS_DIR = BASE_DIR / "photos"
DATA_DIR = BASE_DIR / "data"

for d in (LOGS_DIR, PREVIEW_DIR, PHOTOS_DIR, DATA_DIR):
    d.mkdir(exist_ok=True)
