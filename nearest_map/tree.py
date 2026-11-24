"""k-d дерево: вставка, удаление, поиск в прямоугольнике и ближайшего соседа."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math
from typing import Any


def _coordinates(values: Sequence[float]) -> tuple[float, ...]:
    """Проверить координаты и привести их к конечным вещественным числам."""
    if not values or any(isinstance(value, bool) for value in values):
        raise ValueError("Coordinates must be a non-empty sequence of numbers")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("Coordinates must be finite")
    return result


@dataclass(frozen=True)
class SpatialPoint:
    """Точка с уникальным идентификатором и произвольными прикладными данными."""

    identifier: str
    coordinates: tuple[float, ...]
    data: Any = None

    def __post_init__(self) -> None:
        """Проверить идентификатор и сохранить неизменяемые координаты."""
        if not isinstance(self.identifier, str) or not self.identifier:
            raise ValueError("Point identifier must be a non-empty string")
        object.__setattr__(self, "coordinates", _coordinates(self.coordinates))


@dataclass(slots=True)
class _Node:
    """Узел с осью разбиения и двумя поддеревьями."""

    point: SpatialPoint
    axis: int
    left: "_Node | None" = None
    right: "_Node | None" = None


def _order(point: SpatialPoint, axis: int) -> tuple[float, str]:
    """Упорядочить точки по оси, разрешая равенство идентификатором."""
    return point.coordinates[axis], point.identifier


def _balanced(points: list[SpatialPoint], depth: int, dimensions: int) -> _Node | None:
    """Построить сбалансированное дерево по медианам координат."""
    if not points:
        return None
    axis = depth % dimensions
    points.sort(key=lambda point: _order(point, axis))
    middle = len(points) // 2
    return _Node(points[middle], axis, _balanced(points[:middle], depth + 1, dimensions),
                 _balanced(points[middle + 1:], depth + 1, dimensions))


def _minimum(node: _Node, axis: int) -> SpatialPoint:
    """Найти минимум выбранной координаты с учётом осей поддеревьев."""
    if node.axis == axis:
        return node.point if node.left is None else _minimum(node.left, axis)
    candidates = [node.point]
    if node.left is not None:
        candidates.append(_minimum(node.left, axis))
    if node.right is not None:
        candidates.append(_minimum(node.right, axis))
    return min(candidates, key=lambda point: _order(point, axis))


def _remove(node: _Node | None, point: SpatialPoint) -> _Node | None:
    """Удалить узел, заменив его минимумом по текущей оси при необходимости."""
    if node is None:
        return None
    if node.point.identifier == point.identifier:
        if node.right is not None:
            node.point = _minimum(node.right, node.axis)
            node.right = _remove(node.right, node.point)
        elif node.left is not None:
            node.point = _minimum(node.left, node.axis)
            node.right = _remove(node.left, node.point)
            node.left = None
        else:
            return None
    elif _order(point, node.axis) < _order(node.point, node.axis):
        node.left = _remove(node.left, point)
    else:
        node.right = _remove(node.right, point)
    return node


def _inside(point: SpatialPoint, limits: tuple[tuple[float, ...], tuple[float, ...]]) -> bool:
    """Проверить принадлежность замкнутому прямоугольнику/параллелепипеду."""
    return all(low <= value <= high for value, low, high in zip(point.coordinates, *limits))


def _range(node: _Node | None, limits: tuple[tuple[float, ...], tuple[float, ...]],
           result: list[SpatialPoint]) -> None:
    """Обойти только поддеревья, пересекающие запрошенную область."""
    if node is None:
        return
    if _inside(node.point, limits):
        result.append(node.point)
    split = node.point.coordinates[node.axis]
    if limits[0][node.axis] <= split:
        _range(node.left, limits, result)
    if limits[1][node.axis] >= split:
        _range(node.right, limits, result)


def _nearest(node: _Node | None, query: tuple[float, ...],
             limits: tuple[tuple[float, ...], tuple[float, ...]] | None,
             best: tuple[SpatialPoint, float] | None) -> tuple[SpatialPoint, float] | None:
    """Искать ближайшую точку с отсечением по расстоянию до разделяющей плоскости."""
    if node is None:
        return best
    if limits is None or _inside(node.point, limits):
        distance = sum((left - right) ** 2 for left, right in zip(query, node.point.coordinates))
        if best is None or (distance, node.point.identifier) < (best[1], best[0].identifier):
            best = node.point, distance
    split = node.point.coordinates[node.axis]
    difference = query[node.axis] - split
    children = [(node.left, limits is None or limits[0][node.axis] <= split),
                (node.right, limits is None or limits[1][node.axis] >= split)]
    if difference > 0:
        children.reverse()
    if children[0][1]:
        best = _nearest(children[0][0], query, limits, best)
    if children[1][1] and (best is None or difference ** 2 <= best[1]):
        best = _nearest(children[1][0], query, limits, best)
    return best


class KDTree:
    """k-d дерево с уникальными ID, евклидовой метрикой и диапазонным поиском."""

    def __init__(self, points: Iterable[SpatialPoint] = (), dimensions: int = 2) -> None:
        """Построить дерево заданной размерности по набору точек."""
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions < 1:
            raise ValueError("dimensions must be a positive integer")
        self._dimensions = dimensions
        self._points: dict[str, SpatialPoint] = {}
        for point in points:
            self._check_point(point)
            self._points[point.identifier] = point
        self._root = _balanced(list(self._points.values()), 0, dimensions)

    @property
    def dimensions(self) -> int:
        """Количество пространственных координат точки."""
        return self._dimensions

    @property
    def size(self) -> int:
        """Количество точек в дереве."""
        return len(self._points)

    def __len__(self) -> int:
        """Вернуть количество хранимых точек."""
        return self.size

    def _check_point(self, point: SpatialPoint) -> None:
        """Проверить размерность и уникальность вставляемой точки."""
        if len(point.coordinates) != self.dimensions:
            raise ValueError("Point dimension does not match the tree")
        if point.identifier in self._points:
            raise ValueError(f"Duplicate identifier: {point.identifier}")

    def _query(self, values: Sequence[float]) -> tuple[float, ...]:
        """Проверить размерность и значения координат запроса."""
        coordinates = _coordinates(values)
        if len(coordinates) != self.dimensions:
            raise ValueError("Query dimension does not match the tree")
        return coordinates

    def _limits(self, lower: Sequence[float], upper: Sequence[float]) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """Проверить границы области поиска."""
        low, high = self._query(lower), self._query(upper)
        if any(left > right for left, right in zip(low, high)):
            raise ValueError("Lower bounds must not exceed upper bounds")
        return low, high

    def insert(self, point: SpatialPoint) -> None:
        """Вставить точку, перебалансировав дерево при чрезмерной глубине."""
        self._check_point(point)
        self._points[point.identifier] = point
        if self._root is None:
            self._root = _Node(point, 0)
            return
        node, depth = self._root, 0
        while True:
            side = "left" if _order(point, node.axis) < _order(node.point, node.axis) else "right"
            child = getattr(node, side)
            depth += 1
            if child is None:
                setattr(node, side, _Node(point, depth % self.dimensions))
                break
            node = child
        if depth > max(8, 2 * math.ceil(math.log2(self.size + 1))):
            self._root = _balanced(list(self._points.values()), 0, self.dimensions)

    def remove(self, identifier: str) -> SpatialPoint:
        """Удалить точку по ID; при отсутствии возбудить KeyError."""
        point = self._points[identifier]
        self._root = _remove(self._root, point)
        del self._points[identifier]
        return point

    def range_search(self, lower: Sequence[float], upper: Sequence[float]) -> list[SpatialPoint]:
        """Найти все точки в замкнутой области, заданной двумя углами."""
        limits = self._limits(lower, upper)
        result: list[SpatialPoint] = []
        _range(self._root, limits, result)
        return result

    def nearest(self, query: Sequence[float], lower: Sequence[float] | None = None,
                upper: Sequence[float] | None = None) -> tuple[SpatialPoint, float] | None:
        """Вернуть ближайшую точку и евклидово расстояние либо None для пустого результата."""
        coordinates = self._query(query)
        if (lower is None) != (upper is None):
            raise ValueError("Specify both bounds or neither")
        limits = self._limits(lower, upper) if lower is not None and upper is not None else None
        result = _nearest(self._root, coordinates, limits, None)
        return None if result is None else (result[0], math.sqrt(result[1]))
