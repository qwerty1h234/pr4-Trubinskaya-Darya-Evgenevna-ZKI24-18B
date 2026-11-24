"""Получение объектов OpenStreetMap через открытый Overpass API."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Area, CATEGORIES, Coordinates, MapObject, number

ENDPOINTS = ("https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter")
MAX_OBJECTS = 10_000
MAX_RESPONSE = 12 * 1024 * 1024


class MapDataError(RuntimeError):
    """Ошибка получения полного и корректного набора объектов карты."""


def build_query(area: Area, category: str) -> str:
    """Сформировать ограниченный по времени запрос по разрешённой категории."""
    if category not in CATEGORIES:
        raise ValueError("Выберите известный тип объекта.")
    _, key, value = CATEGORIES[category]
    bounds = f"{area.south},{area.west},{area.north},{area.east}"
    return (f'[out:json][timeout:10][maxsize:67108864];'
            f'nwr["{key}"="{value}"]({bounds});out center {MAX_OBJECTS + 1};')


def _download(endpoint: str, query: str) -> dict[str, Any]:
    """Получить JSON по HTTPS с тайм-аутом и ограничением размера ответа."""
    request = Request(endpoint, data=urlencode({"data": query}).encode("utf-8"), headers={
        "User-Agent": "NearestMap/1.0 (OpenStreetMap educational application)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=12) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise MapDataError("Слишком много данных. Уменьшите область поиска.")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise MapDataError("Сервис карты вернул некорректный ответ. Повторите запрос позже.")
    if data.get("remark"):
        raise MapDataError("Сервис не завершил запрос. Уменьшите область или повторите запрос позже.")
    if len(data["elements"]) > MAX_OBJECTS:
        raise MapDataError("Найдено более 10 000 объектов. Уменьшите область поиска.")
    return data


def _address(tags: dict[str, Any]) -> str:
    """Собрать только указанные в OSM адресные поля без выдуманных значений."""
    if tags.get("addr:full"):
        return str(tags["addr:full"])
    street = tags.get("addr:street") or tags.get("addr:place")
    parts = [tags.get("addr:city"), street, tags.get("addr:housenumber")]
    return ", ".join(str(part) for part in parts if part) or "Адрес не указан в OpenStreetMap"


def parse_objects(data: dict[str, Any], area: Area, category: str) -> list[MapObject]:
    """Прочитать точки и центры площадных объектов; отобрать их по области."""
    objects = {}
    label, key, value = CATEGORIES[category]
    for element in data["elements"]:
        if not isinstance(element, dict):
            continue
        kind, identifier = element.get("type"), element.get("id")
        tags = element.get("tags", {})
        if kind not in ("node", "way", "relation") or not isinstance(identifier, int):
            continue
        if not isinstance(tags, dict) or tags.get(key) != value:
            continue
        coordinates = element if kind == "node" else element.get("center", {})
        try:
            point = Coordinates(number(coordinates["lat"]), number(coordinates["lon"]))
        except (KeyError, TypeError, ValueError):
            continue
        if area.contains(point):
            identity = f"{kind}/{identifier}"
            name = str(tags.get("name") or tags.get("brand") or tags.get("operator") or label)
            objects[identity] = MapObject(identity, name, _address(tags), category, point)
    return list(objects.values())


def load_objects(area: Area, category: str) -> list[MapObject]:
    """Загрузить объекты, используя резервный сервис при временной сетевой ошибке."""
    query = build_query(area, category)
    for endpoint in ENDPOINTS:
        try:
            return parse_objects(_download(endpoint, query), area, category)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, MapDataError):
            continue
    try:
        return parse_objects(_map_download(area, category), area, category)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
        raise MapDataError("Не удалось получить данные OpenStreetMap. Проверьте интернет "
                           "или повторите поиск позже.") from error


def _geometry(element: dict[str, Any], index: dict[tuple[str, int], dict[str, Any]],
              seen: frozenset[tuple[str, int]] = frozenset()) -> list[Coordinates]:
    """Получить полную геометрию объекта из ответа основного API."""
    identity = element["type"], element["id"]
    if identity in seen:
        raise MapDataError("Неполная геометрия области. Повторите запрос позже через Overpass.")
    if identity[0] == "node":
        return [Coordinates(number(element["lat"]), number(element["lon"]))]
    references = ([("node", identifier) for identifier in element.get("nodes", [])]
                  if identity[0] == "way" else [(member["type"], member["ref"]) for member in element.get("members", [])])
    points = []
    for reference in references:
        if reference not in index:
            raise MapDataError("API вернул неполную геометрию. Уменьшите область или повторите поиск позже.")
        points.extend(_geometry(index[reference], index, seen | {identity}))
    return points


def _map_download(area: Area, category: str) -> dict[str, Any]:
    """Резервный запрос небольшого участка через основной read-only API OSM."""
    if (area.north - area.south) * (area.east - area.west) > 0.001:
        raise MapDataError("Overpass временно недоступен. Приблизьте карту и выберите меньшую область.")
    query = urlencode({"bbox": f"{area.west},{area.south},{area.east},{area.north}"})
    request = Request("https://api.openstreetmap.org/api/0.6/map.json?" + query,
                      headers={"User-Agent": "NearestMap/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise MapDataError("Слишком много данных. Приблизьте карту и уменьшите область.")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise MapDataError("Некорректный ответ API карты.")
    index = {(item["type"], item["id"]): item for item in data["elements"]}
    _, key, value = CATEGORIES[category]
    selected = []
    for item in data["elements"]:
        if item.get("tags", {}).get(key) != value:
            continue
        if item["type"] != "node":
            points = _geometry(item, index)
            if not points:
                continue
            item["center"] = {"lat": (min(point.lat for point in points) + max(point.lat for point in points)) / 2,
                              "lon": (min(point.lon for point in points) + max(point.lon for point in points)) / 2}
        selected.append(item)
        if len(selected) > MAX_OBJECTS:
            raise MapDataError("Найдено более 10 000 объектов. Уменьшите область поиска.")
    return {"elements": selected}
