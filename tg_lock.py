"""Очередь на вход в Telegram под аккаунтом пользователя (Telethon, файл data/telegram_session). Сбор новинок,
постановка в очередь, слежка за поставщиками и разведчик берут этот замок, чтобы не читать Telegram одновременно
(файл сессии — одна база SQLite). Завис дольше 30 минут — считается брошенным."""

import os
import time
from contextlib import contextmanager

import config

LOCK = config.DATA_DIR / "telethon.lock"
STALE = 30 * 60


@contextmanager
def telegram_lock(wait: int = 600):
    start = time.time()
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime > STALE:
                    LOCK.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() - start > wait:
                raise TimeoutError("Telegram занят другим скриптом")
            time.sleep(2)
    try:
        yield
    finally:
        LOCK.unlink(missing_ok=True)


def client():
    """Готовый TelegramClient пользователя (без запроса кода: если вход слетел — ошибка, а не зависание)."""
    from telethon.sync import TelegramClient
    c = TelegramClient(str(config.DATA_DIR / "telegram_session"), int(config.TELEGRAM_API_ID), config.TELEGRAM_API_HASH)
    c.connect()
    if not c.is_user_authorized():
        c.disconnect()
        raise RuntimeError("вход в Telegram слетел — нужен повторный вход (telegram_login.bat)")
    return c


def post_link(channel_id: int, msg_id: int, username: str | None = None) -> str:
    """Ссылка на пост канала (для закрытого — t.me/c/…, открывается у тех, кто подписан)."""
    if username:
        return f"https://t.me/{username}/{msg_id}"
    return f"https://t.me/c/{str(channel_id).removeprefix('-100')}/{msg_id}"
