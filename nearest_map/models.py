"""Географические координаты, области и объекты карты."""

from dataclasses import dataclass
import math
from typing import Any

EARTH_RADIUS = 6_371_000.0
CATEGORIES = {
    "cafe": ("Кафе", "amenity", "cafe"),
    "restaurant": ("Рестораны", "amenity", "restaurant"),
    "supermarket": ("Супермаркеты", "shop", "supermarket"),
    "pharmacy": ("Аптеки", "amenity", "pharmacy"),
    "hospital": ("Больницы", "amenity", "hospital"),
    "atm": ("Банкоматы", "amenity", "atm"),
}


def number(value: Any) -> float:
    """Преобразовать число из запроса и отклонить бесконечность, NaN и bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Координаты должны быть числами.")
    try:
        result = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("Координаты должны быть числами.") from error
    if not math.isfinite(result):
        raise ValueError("Координаты должны быть конечными числами.")
    return result


@dataclass(frozen=True)
class Coordinates:
    """Широта и долгота в градусах в пределах отображаемой карты."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        """Проверить географические ограничения."""
        if not math.isfinite(self.lat) or not math.isfinite(self.lon):
            raise ValueError("Некорректные координаты.")
        if not -85 <= self.lat <= 85 or not -180 <= self.lon <= 180:
            raise ValueError("Широта должна быть от −85 до 85, долгота — от −180 до 180.")

    def project(self, origin: "Coordinates") -> tuple[float, float]:
        """Преобразовать координаты в локальную плоскость в метрах."""
        horizontal = EARTH_RADIUS * math.radians(self.lon - origin.lon) * math.cos(math.radians(origin.lat))
        vertical = EARTH_RADIUS * math.radians(self.lat - origin.lat)
        return horizontal, vertical


@dataclass(frozen=True)
class Area:
    """Прямоугольная область без пересечения линии смены дат."""

    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        """Проверить границы и ограничить размер области сорока километрами."""
        bottom = Coordinates(self.south, self.west)
        top = Coordinates(self.north, self.east)
        if self.south >= self.north or self.west >= self.east:
            raise ValueError("Южная и западная границы должны быть меньше северной и восточной.")
        center = Coordinates((self.south + self.north) / 2, (self.west + self.east) / 2)
        left, right = bottom.project(center), top.project(center)
        if right[0] - left[0] > 40_000 or right[1] - left[1] > 40_000:
            raise ValueError("Уменьшите область: не более 40 км по каждой стороне.")

    def contains(self, point: Coordinates) -> bool:
        """Проверить принадлежность точки области, включая границы."""
        return self.south <= point.lat <= self.north and self.west <= point.lon <= self.east

    def bounds(self, origin: Coordinates) -> tuple[tuple[float, float], tuple[float, float]]:
        """Вернуть границы области в локальных метрических координатах."""
        return Coordinates(self.south, self.west).project(origin), Coordinates(self.north, self.east).project(origin)


@dataclass(frozen=True)
class MapObject:
    """Объект OpenStreetMap с координатами, названием и доступным адресом."""

    identifier: str
    name: str
    address: str
    category: str
    location: Coordinates

    def as_dict(self) -> dict[str, Any]:
        """Подготовить данные объекта для браузера."""
        return {"id": self.identifier, "name": self.name, "address": self.address,
                "category": self.category, "lat": self.location.lat, "lon": self.location.lon,
                "url": f"https://www.openstreetmap.org/{self.identifier}"}
