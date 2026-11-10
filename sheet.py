"""Связь с Google-таблицей заказов через веб-приложение Apps Script (код скрипта — sheet_script.gs в корне проекта).
Адрес и секрет — SHEET_WEBAPP_URL и SHEET_SECRET в .env. Секрет в лог не пишется."""

import re
import json

import requests

import config


def call(action: str, _demo: bool = False, **kw) -> dict:
    """Возвращает ответ скрипта: {"ok": True, ...} или {"ok": False, "error": "..."}.
    _demo=True — в КОПИЮ таблицы для показа/проверки (SHEET_DEMO_URL), никогда не в настоящую."""
    url = config.SHEET_DEMO_URL if _demo else config.SHEET_WEBAPP_URL
    if not url or not config.SHEET_SECRET:
        return {"ok": False, "error": "таблица не подключена (нет адреса в .env)"}
    body = json.dumps({"secret": config.SHEET_SECRET, "action": action, **kw}, ensure_ascii=False).encode("utf-8")
    try:
        resp = requests.post(url, data=body, headers={"Content-Type": "application/json"}, timeout=90)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"нет связи с таблицей ({type(exc).__name__})"}
    try:
        return resp.json()
    except ValueError:
        return {"ok": False, "error": f"таблица ответила не так (HTTP {resp.status_code}) — проверь развертывание скрипта"}


def money(s) -> int:
    """«2 600 ₽» -> 2600, «-» / пусто -> 0."""
    if isinstance(s, (int, float)):
        return int(s)
    digits = re.sub(r"[^\d-]", "", str(s or "")).strip("-")
    return int(digits) if digits else 0
