"""
Треки для роликов «под трек» (07.10.2026, пользователь: «делай ежедневные под треки, потом посмотрим, какие звуки
убрать, какие оставить и какие добавить»).

Каждый трек — ролик из ТикТока/CapCut с трендовым звуком. Из него scripts/beat_grid.py вытаскивает темп, доли и дроп
(data/beats/<имя>.json), по ним make_videos.card_beat режет наш ролик ровно в такт. Ролик выходит без звука:
владелец ставит этот же звук в ТикТоке с начала.

Список: data/beats/tracks.json — [{stem, name, on, added}]. Управление из админ-бота:
  • прислать боту (в личку или в чат «Ролики») видео/аудио/голосовое — без подписи или с «трек <название>» —
    добавится (скачать через Bot API можно файлы до 20 МБ);
  • «треки» — список с кнопками ✖ Убрать / ✅ Вернуть (snd:off:<stem> / snd:on:<stem>).
Ежедневный пакет берёт включённые треки по очереди (реже всего использованный — первым; учёт в video_log).
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import config
import bot

DIR = config.DATA_DIR / "beats"
SRC = DIR / "src"
REG = DIR / "tracks.json"
FIRST = {  # треки, присланные 07.10 ночью (ролики на рабочем столе) — подписи по содержимому роликов
    "video_2026-10-07_02-17-56": "твой звук из поста «Угадай цену» (TNF)", "video_2026-10-07_02-18-04": "девушка в чёрном",
    "video_2026-10-07_02-18-15": "шаблон «PHOTO 1…8»", "video_2026-10-07_02-18-18": "эдит CapCut, девушка в Nike",
    "video_2026-10-07_02-18-22": "блондинка танцует", "video_2026-10-07_02-18-25": "машины (фиолетовая)",
    "video_2026-10-07_02-18-29": "BMW",
}


def load() -> list[dict]:
    if REG.exists():
        return json.loads(REG.read_text(encoding="utf-8"))
    tracks = []  # первый запуск: собрать из уже разобранных треков, исходники — в data/beats/src (рабочий стол чистят)
    SRC.mkdir(parents=True, exist_ok=True)
    for js in sorted(DIR.glob("*.json")):
        if js.name == REG.name:
            continue
        g = json.loads(js.read_text(encoding="utf-8"))
        src = Path(g.get("source", ""))
        if src.exists() and src.parent != SRC:
            dst = SRC / src.name
            shutil.copy2(src, dst)
            g["source"] = str(dst)
            js.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        tracks.append({"stem": js.stem, "name": FIRST.get(js.stem, js.stem), "on": True, "added": datetime.now().isoformat(timespec="seconds")})
    save(tracks)
    return tracks


def save(tracks: list[dict]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(tracks, ensure_ascii=False, indent=1), encoding="utf-8")


def grid(stem: str) -> dict:
    return json.loads((DIR / f"{stem}.json").read_text(encoding="utf-8"))


def uses(conn, stem: str) -> tuple[int, str]:
    row = conn.execute("SELECT count(*), max(created) FROM video_log WHERE kind=?", (f"beat:{stem}",)).fetchone()
    return row[0], row[1] or ""


FRESH_DAYS = 21  # трендовый звук живёт от нескольких дней до 2–3 недель (обзоры ТикТока, 09.10)
STALE_NOTE = DIR / "stale_reminder.last"


def age_days(t: dict) -> int:
    try:
        return (datetime.now() - datetime.fromisoformat(t["added"])).days
    except (KeyError, ValueError):
        return 0


def next_track(conn) -> dict | None:
    """Включённый трек, который реже всего шёл в ролики (при равенстве — тот, что давно не был). С 09.10 — сначала
    свежие (моложе FRESH_DAYS): под выдохшийся звук ролик в ленту уже не попадает; свежих нет — любой включённый."""
    on = [t for t in load() if t["on"] and (DIR / f"{t['stem']}.json").exists()]
    fresh = [t for t in on if age_days(t) < FRESH_DAYS]
    pool = fresh or on
    return min(pool, key=lambda t: uses(conn, t["stem"])) if pool else None


def remind_if_stale() -> bool:
    """Самому свежему треку больше 10 дней — раз в неделю попросить новые звуки (из tick.py)."""
    tracks = [t for t in load() if t["on"]]
    newest = min((age_days(t) for t in tracks), default=99)
    if newest < 10:
        return False
    if STALE_NOTE.exists() and (datetime.now() - datetime.fromisoformat(STALE_NOTE.read_text(encoding="utf-8").strip())).days < 7:
        return False
    text = (f"🎧 Самому свежему звуку уже {newest} дн. — трендовые звуки выдыхаются за 2–3 недели, и ролик под старый "
            "звук лента почти не показывает.\n\nПришли 2–3 свежих: в ТикТоке открой поиск → «Звуки» (или ролики "
            "конкурентов, которые сейчас залетают) → сохрани ролик с этим звуком → перешли сюда (можно аудиофайлом; подпись «трек название» — по желанию).")
    if bot.call("sendMessage", {"chat_id": bot.content_chat_id(), "text": text}).get("ok"):  # в чат «Ролики»
        STALE_NOTE.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
        return True
    return False


# ---------- админ-бот ----------

MEDIA_TYPES = ("video", "audio", "voice", "video_note")


def media_of(msg: dict) -> dict | None:
    doc = msg.get("document") or {}
    if doc.get("mime_type", "").startswith(("video/", "audio/")):
        return doc
    return next((msg[k] for k in MEDIA_TYPES if msg.get(k)), None)


def is_track_message(msg: dict) -> bool:
    """11.10: трек — любое видео/аудио/голосовое без подписи или с подписью «трек …»/«звук …» (раньше подпись была
    обязательной). Видео с другой подписью — не трек."""
    cap = (msg.get("caption") or "").strip().lower()
    return media_of(msg) is not None and (not cap or cap.startswith("трек") or cap.startswith("звук"))


def add_from_message(conn, msg: dict) -> None:
    """Видео/аудио (подпись «трек <название>» — по желанию) -> скачать, разобрать ритм, включить в очередь."""
    import requests
    import beat_grid
    chat_id = msg["chat"]["id"]
    media = media_of(msg)
    if (media.get("file_size") or 0) > 20 * 1024 * 1024:
        bot.call("sendMessage", {"chat_id": chat_id, "text": "🎧 Файл больше 20 МБ — бот такой скачать не может. "
                                 "Обрежь ролик до 15–20 секунд или пришли сжатым (как обычное видео, не файлом)."})
        return
    path = bot.call("getFile", {"file_id": media["file_id"]}).get("result", {}).get("file_path")
    if not path:
        bot.call("sendMessage", {"chat_id": chat_id, "text": "🎧 Не получилось скачать видео — пришли ещё раз."})
        return
    SRC.mkdir(parents=True, exist_ok=True)
    stem = f"track_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    dst = SRC / f"{stem}{Path(path).suffix or '.mp4'}"  # mp3/m4a/ogg тоже: ffmpeg берёт звук из любого
    try:
        dst.write_bytes(requests.get(f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{path}", timeout=120).content)
        g = beat_grid.analyse(dst)
        if g["duration"] < 5 or len(g["beats"]) < 8:
            raise ValueError("слишком короткий или без ритма")
    except Exception as exc:  # битый файл, нет звука и т. п.
        dst.unlink(missing_ok=True)
        bot.call("sendMessage", {"chat_id": chat_id, "text": f"🎧 Не разобрал звук в этом видео ({type(exc).__name__}). "
                                 "Пришли другой ролик с этим треком."})
        return
    (DIR / f"{stem}.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    cap = (msg.get("caption") or "").strip()
    au = msg.get("audio") or {}
    tag = " — ".join(x for x in (au.get("performer"), au.get("title")) if x) or Path(media.get("file_name") or "").stem
    name = (cap.split(maxsplit=1)[1].strip() if len(cap.split(maxsplit=1)) > 1 else tag or f"трек от {datetime.now():%d.%m %H:%M}")[:60]
    tracks = load()
    tracks.append({"stem": stem, "name": name, "on": True, "added": datetime.now().isoformat(timespec="seconds")})
    save(tracks)
    bot.call("sendMessage", {"chat_id": chat_id, "text": f"🎧 Добавил трек «{name}»: {g['bpm']:.0f} уд/мин, дроп на "
                             f"{g['drop']:.1f} с, длина {g['duration']:.0f} с. Пойдёт в ежедневные ролики по очереди. "
                             "Выбрать его для готового ролика — «🎵 Другой звук» под роликом. Все треки — слово «треки»."})


def send_list(conn, chat_id: int, msg_id: int | None = None) -> None:
    tracks = load()
    lines = ["🎧 <b>Треки для роликов</b> (ежедневные идут по очереди, без звука — ставишь этот звук в ТикТоке):", ""]
    rows = []
    for k, t in enumerate(tracks, 1):
        n, last = uses(conn, t["stem"])
        g = grid(t["stem"]) if (DIR / f"{t['stem']}.json").exists() else {}
        mark = "✅" if t["on"] else "⏸"
        age = age_days(t)
        old = " · ⌛ выдохся, замени" if age >= FRESH_DAYS else ""
        lines.append(f"{mark} {k}. {t['name']} — {g.get('bpm', 0):.0f} уд/мин, роликов: {n}, {age} дн.{old}")
        rows.append([{"text": f"{'✖ Убрать' if t['on'] else '✅ Вернуть'} {k}", "callback_data": f"snd:{'off' if t['on'] else 'on'}:{k}"}])
    lines += ["", "Добавить: пришли сюда ролик, аудиофайл или голосовое с нужным звуком (подпись «трек название» — по желанию).",
              f"Звуки живут 2–3 недели: старше {FRESH_DAYS} дн. идут в ролики, только если свежих нет."]
    payload = {"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML",
               "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False)}
    if msg_id:
        bot.call("editMessageText", {**payload, "message_id": msg_id})
    else:
        bot.call("sendMessage", payload)


def handle(conn, cq: dict, chat_id: int, msg_id: int, data: str) -> None:
    _, act, k = data.split(":")
    tracks = load()
    i = int(k) - 1
    if 0 <= i < len(tracks):
        if act == "off" and sum(t["on"] for t in tracks) <= 1:
            bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "show_alert": "true",
                                             "text": "Это последний включённый трек — сначала добавь другой"})
            return
        tracks[i]["on"] = act == "on"
        save(tracks)
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Убрал" if act == "off" else "Вернул"})
    send_list(conn, chat_id, msg_id)
