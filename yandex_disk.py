"""Мини-клиент Яндекс Диска: загрузка файла в папку приложения и публичная ссылка.
Токен берётся из .env (YANDEX_DISK_TOKEN), в лог и на экран не выводится.
Диск иногда отвечает 5xx/429 — каждый запрос повторяется несколько раз."""

import time
from pathlib import Path

import requests

import config

API = "https://cloud-api.yandex.net/v1/disk"
ROOT = "app:/sneakerflow"
RETRIES = 5


def _headers() -> dict:
    return {"Authorization": f"OAuth {config.YANDEX_DISK_TOKEN.strip()}"}


def _request(method: str, url: str, ok: tuple, **kwargs) -> requests.Response:
    """Запрос с повторами при временных ошибках (5xx, 429, обрыв сети)."""
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.RequestException as exc:
            last = f"сетевая ошибка {type(exc).__name__}"
        else:
            if resp.status_code in ok:
                return resp
            last = f"{resp.status_code} {resp.text[:150]}"
            # 423 «ресурс заблокирован» — тоже временная: папку держит другая операция (только что закончили грузить
            # и публиковать фото в неё). 20.10 из-за неё 2 модели ушли на Авито без фото с рамкой
            if resp.status_code < 500 and resp.status_code not in (429, 423):
                break  # ошибка не временная — повторять бессмысленно
        time.sleep(2 * (attempt + 1) if not last.startswith("423") else 5 * (attempt + 1))
    raise RuntimeError(f"Диск: {method} не удался: {last}")


def _ensure_dir(remote_dir: str) -> None:
    """Создаёт вложенные папки по одной (Диск не умеет mkdir -p)."""
    current = ROOT
    for part in remote_dir.strip("/").split("/"):
        current = f"{current}/{part}"
        _request("PUT", f"{API}/resources", (201, 409), headers=_headers(), params={"path": current}, timeout=30)


def upload(local: Path, remote_dir: str, remote_name: str) -> str:
    """Загружает файл, делает его публичным и возвращает публичную ссылку."""
    _ensure_dir(remote_dir)
    path = f"{ROOT}/{remote_dir.strip('/')}/{remote_name}"

    r = _request("GET", f"{API}/resources/upload", (200,), headers=_headers(),
                 params={"path": path, "overwrite": "true"}, timeout=30)
    href = r.json()["href"]
    for attempt in range(RETRIES):  # сам файл передаём отдельно (файл открывается заново на каждую попытку)
        with local.open("rb") as f:
            try:
                put = requests.put(href, data=f, timeout=600)
            except requests.RequestException:
                put = None
        if put is not None and put.status_code in (201, 202):
            break
        time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"Загрузка {local.name} на Диск не удалась")

    _request("PUT", f"{API}/resources/publish", (200,), headers=_headers(), params={"path": path}, timeout=30)
    for attempt in range(12):  # публичная ссылка появляется не мгновенно (иногда через 10–20 секунд)
        info = _request("GET", f"{API}/resources", (200, 404), headers=_headers(),
                        params={"path": path, "fields": "public_url"}, timeout=30)
        if info.status_code == 200 and "public_url" in info.json():
            return info.json()["public_url"]
        if attempt == 5:  # ссылка так и не появилась — публикуем ещё раз
            _request("PUT", f"{API}/resources/publish", (200,), headers=_headers(), params={"path": path}, timeout=30)
        time.sleep(2)
    raise RuntimeError(f"Диск не отдал публичную ссылку для {remote_name}")
