"""Подключение нового канала поставщика к сбору из бота (кнопка «➕ В сбор» в отчёте разведчика) и название
поставщика для таблицы заказов. Меняет data/supplier_channels.json и data/supplier_names.json — только по кнопке/ответу
владельца."""

import json
from datetime import datetime, timedelta

import config

CHANNELS = config.DATA_DIR / "supplier_channels.json"
NAMES = config.DATA_DIR / "supplier_names.json"
AWAIT = config.DATA_DIR / "supplier_name_await.json"


def add_channel(channel_id: int, name: str) -> bool:
    """True — добавлен, False — уже был в сборе."""
    chans = json.loads(CHANNELS.read_text(encoding="utf-8"))
    if any(c["id"] == channel_id for c in chans):
        return False
    chans.append({"name": name, "id": channel_id})
    CHANNELS.write_text(json.dumps(chans, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def ask_name(channel_id: int, channel_name: str) -> None:
    AWAIT.write_text(json.dumps({"id": channel_id, "channel": channel_name,
                                 "until": (datetime.now() + timedelta(minutes=30)).isoformat()}, ensure_ascii=False),
                     encoding="utf-8")


def awaiting() -> dict | None:
    if not AWAIT.exists():
        return None
    a = json.loads(AWAIT.read_text(encoding="utf-8"))
    if datetime.fromisoformat(a["until"]) < datetime.now():
        AWAIT.unlink(missing_ok=True)
        return None
    return a


def set_table_name(text: str) -> str:
    a = awaiting()
    AWAIT.unlink(missing_ok=True)
    if not a:
        return ""
    name = text.strip()[:40]
    if name.lower() in ("отмена", "потом", "cancel"):
        return "Ок. Название для таблицы можно будет задать потом — просто скажи мне."
    data = json.loads(NAMES.read_text(encoding="utf-8"))
    data["by_channel"][str(a["id"])] = name
    new = name not in data["list"]
    if new:
        data["list"].append(name)
    NAMES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return (f"✅ Канал «{a['channel']}» в таблице — «{name}»."
            + (f"\n⚠️ Такого поставщика в таблице ещё нет — впиши «{name}» в блок «Поставщики» (жёлтые ячейки справа), "
               "иначе таблица не примет заказ с ним." if new else ""))
