"""
Отслеживание посылок по трек-номеру (идея №3): где посылка и что с ней — для подсказок владельцу, НЕ для записи в
таблицу (статус меняет владелец одной кнопкой: таблица — это деньги).

Службы:
  • Почта России — открытая страница отслеживания pochta.ru (та же, что на сайте), без ключей. Трек: 14 цифр
    («80512725062271») или международный «RA123456789RU». Проверено 25.09.2026 на живом треке.
  • СДЭК — страница сайта; через VPN отвечает «Forbidden» (защита от ботов), без VPN — попробуем (в логе видно).
  • Яндекс, Авито Доставка (собственные пункты), Boxberry, 5post — открытого способа нет: такие треки пропускаем.

События (от ранних к поздним): arrived — ждёт в пункте выдачи; delivered — клиент забрал; returning — едет назад;
returned — вернулось отправителю.
"""

import re
from datetime import datetime

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*", "Accept-Language": "ru-RU,ru;q=0.9"}
ORDER = ["transit", "arrived", "delivered", "returning", "returned"]
EVENT_TEXT = {"transit": "в пути", "arrived": "ждёт в пункте выдачи", "delivered": "клиент забрал",
              "returning": "едет назад отправителю", "returned": "вернулось отправителю"}


def carrier(track: str, service: str | None = None) -> str | None:
    t = re.sub(r"[\s\-]", "", track or "").upper()
    svc = (service or "").lower()
    if re.fullmatch(r"\d{14}", t) or re.fullmatch(r"[A-Z]{2}\d{9}RU", t):
        return "pochta"
    if re.fullmatch(r"\d{10,11}", t) and ("сдэк" in svc or not svc or "авито" in svc):
        return "cdek"
    return None


def _pochta(track: str) -> dict:
    r = requests.get("https://www.pochta.ru/api/tracking/api/v1/trackings/by-barcodes",
                     params={"language": "ru", "track-numbers": track}, headers=UA, timeout=30)
    r.raise_for_status()
    items = (r.json().get("detailedTrackings") or [])
    it = (items[0] or {}).get("trackingItem") if items else None
    if not it:
        return {"event": None, "text": "почта не знает такой трек"}
    hist = it.get("trackingHistoryItemList") or []
    texts = [(h.get("humanStatus") or "").lower() for h in hist]
    ops = [(h.get("operationType"), h.get("operationAttr")) for h in hist]
    event = "transit"
    if any(t == 8 and a == 2 for t, a in ops) or any("прибыло в место вручения" in x or "готово к выдаче" in x for x in texts):
        event = "arrived"
    if any(t == 3 for t, _ in ops) or any("возврат" in x for x in texts):
        event = "returning"
    if any(t == 2 and a == 1 for t, a in ops) or any("вручение адресату" in x or "получено адресатом" in x for x in texts):
        event = "delivered" if event != "returning" else event
    if any(t == 2 and a == 2 for t, a in ops) or any("вручение отправителю" in x for x in texts):
        event = "returned"
    last = hist[0] if hist else {}
    return {"event": event, "text": it.get("commonStatus") or last.get("humanStatus") or "",
            "at": (last.get("date") or "")[:16].replace("T", " "), "city": last.get("cityName") or "",
            "storage_until": (it.get("endStorageDate") or "")[:10]}


def _cdek(track: str) -> dict:
    r = requests.get("https://www.cdek.ru/api-site/track/info/", params={"track": track, "locale": "ru"}, headers=UA, timeout=30)
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"СДЭК не отдал статус (HTTP {r.status_code})")
    d = r.json().get("data") or {}
    status = (d.get("status") or {}).get("name") or d.get("statusName") or ""
    low = status.lower()
    event = ("returned" if "вручен отправителю" in low else "returning" if "возврат" in low else
             "delivered" if "вручен" in low else "arrived" if "готов к выдаче" in low or "прибыл в пункт" in low else "transit")
    return {"event": event, "text": status, "at": "", "city": ""}


def check(track: str, service: str | None = None) -> dict:
    """{"event": ..., "text": ..., "at": ..., "carrier": ...} или {"event": None, "skip": причина}."""
    c = carrier(track, service)
    t = re.sub(r"[\s\-]", "", track or "").upper()
    if not c:
        return {"event": None, "skip": "служба без открытого отслеживания"}
    try:
        res = _pochta(t) if c == "pochta" else _cdek(t)
    except Exception as exc:
        return {"event": None, "skip": f"{c}: {type(exc).__name__}: {str(exc)[:80]}"}
    res["carrier"] = c
    res["checked_at"] = datetime.now().isoformat(timespec="minutes")
    return res


def later(a: str | None, b: str | None) -> bool:
    """b — более позднее событие, чем a?"""
    return (ORDER.index(b) if b in ORDER else -1) > (ORDER.index(a) if a in ORDER else -1)
