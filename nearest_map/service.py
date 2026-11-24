"""Проверка запросов карты, ограниченный кэш и поиск с помощью k-d дерева."""

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import Any

from .addresses import resolve_address
from .models import Area, CATEGORIES, Coordinates, MapObject, number
from .osm import load_objects
from .tree import KDTree, SpatialPoint


def _parameters(payload: Any) -> tuple[Coordinates, Area, str]:
    """Проверить структуру запроса, координаты, категорию и границы поиска."""
    if not isinstance(payload, dict):
        raise ValueError("Ожидается объект JSON.")
    category = payload.get("category")
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError("Выберите тип объекта.")
    try:
        point = payload["point"]
        bounds = payload["area"]
        origin = Coordinates(number(point["lat"]), number(point["lon"]))
        area = Area(*(number(bounds[name]) for name in ("south", "west", "north", "east")))
    except (KeyError, TypeError) as error:
        raise ValueError("Укажите точку и прямоугольную область поиска.") from error
    if not area.contains(origin):
        raise ValueError("Точка должна находиться внутри выбранной области поиска.")
    return origin, area, category


class MapService:
    """Поиск по данным открытого API с кэшированием восьми областей на пять минут."""

    def __init__(self, loader: Callable[[Area, str], list[MapObject]] = load_objects) -> None:
        """Задать источник объектов и подготовить потокобезопасный кэш."""
        self._loader = loader
        self._cache: OrderedDict[tuple[Area, str], tuple[float, list[MapObject]]] = OrderedDict()
        self._lock = Lock()

    def clear_cache(self) -> None:
        """Удалить сохранённые наборы объектов."""
        with self._lock:
            self._cache.clear()

    def _objects(self, area: Area, category: str, refresh: bool) -> tuple[list[MapObject], bool]:
        """Получить полный набор объектов из кэша или API."""
        identity = area, category
        with self._lock:
            cached = self._cache.get(identity)
            if not refresh and cached is not None and monotonic() - cached[0] < 300:
                self._cache.move_to_end(identity)
                return cached[1], True
            objects = self._loader(area, category)
            self._cache[identity] = monotonic(), objects
            self._cache.move_to_end(identity)
            while len(self._cache) > 8:
                self._cache.popitem(last=False)
            return objects, False

    def search(self, payload: Any) -> dict[str, Any]:
        """Построить k-d дерево и найти ближайший объект в заданной области."""
        origin, area, category = _parameters(payload)
        refresh = payload.get("refresh", False)
        if not isinstance(refresh, bool):
            raise ValueError("Параметр refresh должен быть логическим.")
        objects, cached = self._objects(area, category, refresh)
        tree = KDTree(SpatialPoint(item.identifier, item.location.project(origin), item) for item in objects)
        lower, upper = area.bounds(origin)
        selected = tree.range_search(lower, upper)
        nearest = tree.nearest((0, 0), lower, upper)
        result = None
        if nearest is not None:
            result = nearest[0].data.as_dict()
            result["address"] = resolve_address(nearest[0].data)
            result["distance_m"] = round(nearest[1], 2)
        return {"nearest": result, "objects": [point.data.as_dict() for point in selected],
                "count": len(selected), "cached": cached,
                "metric": "Евклидово расстояние на локальной плоскости, в метрах; не длина маршрута."}
