"""Мелкие помощники для Telegram-бота (@krossovki_arturka_bot): вызов API и chat_id
владельца (человек, нажавший Start у бота в личке). Токен из .env, в лог не пишется."""

import json

import requests

import config

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
STATE = config.DATA_DIR / "bot_state.json"


def call(method: str, data: dict | None = None, files: dict | None = None, timeout: int = 60) -> dict:
    try:
        res = requests.post(f"{API}/{method}", data=data, files=files, timeout=timeout).json()
    except requests.RequestException as exc:
        # в тексте исключения может быть URL с токеном — возвращаем только тип
        return {"ok": False, "description": f"сетевая ошибка: {type(exc).__name__}"}
    new = (res.get("parameters") or {}).get("migrate_to_chat_id")
    key = next((k for k in ("content_chat_id", "routine_chat_id", "stock_chat_id", "arizona_chat_id")
                if data and str(data.get("chat_id")) == str(_state().get(k))), None) if new else None
    if key:
        # группа «Ролики»/«Рутина»/«Наличие» стала супергруппой (сменила id) — запоминаем новый и повторяем
        _save(**{key: new})
        if files:
            for f in files.values():
                f = f[1] if isinstance(f, tuple) else f
                if hasattr(f, "seek"):
                    f.seek(0)
        return call(method, {**data, "chat_id": new}, files, timeout)
    return res


def _state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def owner_chat_id() -> int | None:
    """chat_id личного чата с владельцем: из data/bot_state.json или из последнего /start."""
    if STATE.exists():
        cid = json.loads(STATE.read_text(encoding="utf-8")).get("owner_chat_id")
        if cid:
            return cid
    res = call("getUpdates", {"limit": 100})
    for upd in reversed(res.get("result", [])):
        msg = upd.get("message") or {}
        if msg.get("chat", {}).get("type") == "private":
            cid = msg["chat"]["id"]
            _save(owner_chat_id=cid)
            return cid
    return None


def _save(**kw) -> None:
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    st.update(kw)
    STATE.write_text(json.dumps(st), encoding="utf-8")


def content_chat_id() -> int | None:
    """11.10: отдельный чат «Ролики» (группа владельца, куда добавлен бот; привязывается командой /content в группе) —
    туда ролики, превью, звуки, чтобы не засорять рабочий бот. Не привязан — личка владельца, как раньше."""
    if STATE.exists():
        cid = json.loads(STATE.read_text(encoding="utf-8")).get("content_chat_id")
        if cid:
            return cid
    return owner_chat_id()


def set_content_chat(cid: int) -> None:
    _save(content_chat_id=cid)


def routine_chat_id() -> int | None:
    """31.10: отдельный чат «Рутина» (группа владельца с ботом; привязывается командой /routine в группе) — туда
    сводка новинок с карточками и отчёт рутины, чтобы не перегружать рабочий бот (там — короткий итог одной строкой).
    Не привязан — личка владельца, как раньше."""
    if STATE.exists():
        cid = json.loads(STATE.read_text(encoding="utf-8")).get("routine_chat_id")
        if cid:
            return cid
    return owner_chat_id()


def set_routine_chat(cid: int) -> None:
    _save(routine_chat_id=cid)


def stock_chat_id() -> int | None:
    """31.10: отдельный чат «Наличие» (группа владельца с ботом; привязывается командой /stock в группе) — туда карточки
    «у Никиты нет: снять?» и списки обновлённых размеров (scripts/nikita_stock.py); в рабочий бот — итог одной строкой.
    Не привязан — личка владельца."""
    if STATE.exists():
        cid = json.loads(STATE.read_text(encoding="utf-8")).get("stock_chat_id")
        if cid:
            return cid
    return owner_chat_id()


def set_stock_chat(cid: int) -> None:
    _save(stock_chat_id=cid)


def arizona_chat_id() -> int | None:
    """07.11: чат «Аризона» (группа владельца с ботом; привязывается командой /arizona в группе) — находки слежки за
    ценами в лавках (arizona/market_watch.py), чтобы игра не мешалась с работой. Не привязан — личка владельца."""
    if STATE.exists():
        cid = json.loads(STATE.read_text(encoding="utf-8")).get("arizona_chat_id")
        if cid:
            return cid
    return owner_chat_id()


def set_arizona_chat(cid: int) -> None:
    _save(arizona_chat_id=cid)


def tell_owner_if_separate(chat_id, text: str) -> None:
    """Короткий итог в рабочий бот, когда подробности ушли в отдельный чат («Рутина»/«Ролики»)."""
    if chat_id and chat_id != owner_chat_id():
        call("sendMessage", {"chat_id": owner_chat_id(), "text": text, "disable_web_page_preview": "true"})
