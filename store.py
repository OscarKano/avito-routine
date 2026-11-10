"""Общая база (data/sneakerflow.db): подключение и поля "просмотра" кандидатов —
то, что определяется по фото глазами (цвет, руки, название, описание)."""

import sqlite3

import config

DB = config.DATA_DIR / "sneakerflow.db"

# цвета, которые принимает Авито (поле Color для кроссовок)
AVITO_COLORS = [
    "Чёрный", "Коричневый", "Бежевый", "Серый", "Белый", "Бордовый", "Красный", "Синий", "Розовый",
    "Жёлтый", "Голубой", "Фиолетовый", "Оранжевый", "Зелёный", "Серебряный", "Золотой", "Разноцветный",
]

REVIEW_COLUMNS = {
    "cover": "INTEGER",     # номер фото, выбранного пользователем главным (первым) для Авито; пусто — как у поставщика
    "color": "TEXT",        # цвет для Авито (из AVITO_COLORS)
    "hands": "TEXT",        # JSON: номера фото, где есть руки/люди (в Telegram не идут)
    "brand": "TEXT",        # бренд по справочнику Авито
    "title_final": "TEXT",  # название объявления для Авито, до 50 символов
    "intro": "TEXT",        # абзац про модель (по фото и данным поставщика)
    "bullets": "TEXT",      # JSON: пункты "Почему стоит брать"
    "season": "TEXT",       # JSON: сезоны для Авито или null
    "reviewed_at": "TEXT",
    "similar": "TEXT",          # JSON: похожие активные объявления на Авито (подсказка против дублей)
    "digest_msg_id": "INTEGER",  # сообщение в личке бота, где пользователь жмёт "взять/убрать"
    "digest_sent_at": "TEXT",
    "digest_caption": "TEXT",  # подпись карточки в сводке — чтобы вернуть её после показа листа с фото (выбор главного фото)
}


def ensure_review_columns(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}
    if not existing:
        return  # таблицу ещё не создал сборщик
    for col, typ in REVIEW_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} {typ}")
    conn.commit()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30)  # ждать до 30 c, если базу держит другой процесс, вместо "database is locked"
    ensure_review_columns(conn)
    return conn
