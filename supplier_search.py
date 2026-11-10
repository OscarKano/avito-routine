"""
Поиск модели по каналам поставщиков в Telegram — как владелец ищет руками (поиск в канале). Нужен потому, что наша
база знает только посты, которые собрала рутина: 31.10 у Никиты «закончились» Lacoste, а у Садовода 26-57 они висели
(«Lacoste Baseshot Winter»), только рутина этот пост не брала.

search({№: "Кроссовки Lacoste бордовые 41-45"}, exclude={каналы Никиты}) -> {№: {"hits": [...], "channels": N, "queries": [...]}}
hit: канал, дата, ссылка на пост, начало текста, фото (файл, если у поста есть фото).

Только читает каналы (вход владельца, data/telegram_session, по очереди с остальными через tg_lock). Цвет по тексту
не проверить — поэтому находки показываем ФОТО, решает владелец.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone

import config
from post_format import format_title
from tg_lock import telegram_lock, client as tg_client, post_link

PHOTOS = config.DATA_DIR / "search_photos"
GENERIC = {"женские", "мужские", "зимние", "унисекс", "кроссовки", "кеды", "ботинки", "сапоги", "угги", "слипоны",
           "low", "high", "mid"}


def model_words(title: str) -> list[str]:
    """«Кроссовки Golden Goose Superstar синие 41-45» -> ['golden', 'goose', 'superstar'] (бренд + модель, без цвета)."""
    m = format_title(title or "").lstrip("• ").split(" (")[0].lower().replace("ё", "е")
    # цифру оставляем и одну: «Air Jordan 1» без «1» находит AJ4 и AJ13
    return [w for w in re.findall(r"[a-zа-я0-9][a-zа-я0-9\-]*", m) if w not in GENERIC and (len(w) >= 2 or w.isdigit())]


def queries_for(title: str) -> list[str]:
    """Что вбивать в поиск канала: вся модель; без бренда (пишут «AJ1», «NB»); номер модели (9060, 1906r, 574)."""
    w = model_words(title)
    out = [" ".join(w)] if w else []
    if len(w) >= 3:
        out.append(" ".join(w[1:]))
    digits = [x for x in w if re.search(r"\d", x) and len(x) >= 3]
    if digits:
        out.append(max(digits, key=len))
    if len(w) >= 3:  # последнее слово мешает (цвет со скрина «синие» -> «Chi-iVie», лишнее «3») — без него
        out.append(" ".join(w[:-1]))
    if len(w) >= 4:  # и без бренда, и без последнего: «Nike Air Max 95 Supreme» -> «air max 95» (бренд часто не пишут)
        out.append(" ".join(w[1:-1]))
    return list(dict.fromkeys(q for q in out if q))


def supplier_channels(exclude: set[int]) -> list[dict]:
    return [c for c in json.loads((config.DATA_DIR / "supplier_channels.json").read_text(encoding="utf-8"))
            if c["id"] not in exclude]


def search(titles: dict[int, str], exclude: set[int], days: int = 60, per_channel: int = 3, total: int = 10) -> dict:
    """Ищет каждую модель во всех каналах поставщиков (кроме exclude) за days дней. Нет входа/VPN — исключение."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    chans = supplier_channels(exclude)
    names = json.loads((config.DATA_DIR / "supplier_names.json").read_text(encoding="utf-8")).get("by_channel", {})
    res = {cid: {"hits": [], "channels": len(chans), "queries": queries_for(t)} for cid, t in titles.items()}
    PHOTOS.mkdir(exist_ok=True)
    with telegram_lock(wait=900):
        cl = tg_client()
        try:
            for ch in chans:
                try:
                    ent = cl.get_entity(ch["id"])
                except Exception:
                    continue  # отписались / канал удалён — ищем в остальных
                who = names.get(str(ch["id"])) or ch["name"]
                for cid, r in res.items():
                    found = []
                    for q in r["queries"]:  # первая фраза, которая что-то нашла в этом канале
                        for m in cl.iter_messages(ent, search=q, limit=10):
                            if m.date < since:
                                break
                            if m.text and m.id not in {x.id for x in found}:
                                found.append(m)
                        time.sleep(0.4)  # поиск в Telegram — не чаще пары раз в секунду, иначе FloodWait
                        if found:
                            break
                    for m in found[:per_channel]:
                        r["hits"].append({"channel": who, "channel_id": ch["id"], "msg": m.id,
                                          "date": m.date.astimezone().strftime("%d.%m"), "ts": m.date.timestamp(),
                                          "link": post_link(ch["id"], m.id, getattr(ent, "username", None)),
                                          "text": re.sub(r"\s+", " ", m.text)[:120], "full": m.text, "_m": m})
            for cid, r in res.items():
                # по кругу: сначала самый свежий пост КАЖДОГО канала, потом вторые… — иначе по бренду («Lacoste»)
                # все места займут два-три канала, а нужная пара у четвёртого не попадёт (31.10: Baseshot у 26-57)
                by_ch = {}
                for h in sorted(r["hits"], key=lambda h: -h["ts"]):
                    by_ch.setdefault(h["channel_id"], []).append(h)
                order = [h for rank in range(per_channel) for hs in by_ch.values() if len(hs) > rank for h in [hs[rank]]]
                for h in order[total:]:
                    h.pop("_m", None)
                r["hits"] = order[:total]
                for h in r["hits"]:
                    m = h.pop("_m")
                    if not m.photo and m.grouped_id:  # подпись альбома — на одном сообщении, фото — на соседних
                        near = cl.get_messages(m.peer_id, ids=list(range(m.id - 9, m.id + 10)))
                        m = next((x for x in near if x and x.grouped_id == m.grouped_id and x.photo), m)
                    if m.photo:
                        p = PHOTOS / f"{h['channel_id']}_{h['msg']}.jpg"
                        if not p.exists():
                            cl.download_media(m, file=str(p))
                        h["photo"] = str(p) if p.exists() else None
            for r in res.values():
                for h in r["hits"]:
                    h.pop("_m", None)
        finally:
            cl.disconnect()
    return res
