"""Проверки k-d дерева по независимому эталонному поиску."""

import math
import random
import unittest

from nearest_map.tree import KDTree, SpatialPoint


class TreeTests(unittest.TestCase):
    """Проверить структуру после вставок, удаления и пространственных запросов."""

    def test_random_operations(self) -> None:
        """Сравнить двумерный и трёхмерный поиск с полным перебором в тесте."""
        generator = random.Random(9123)
        for dimensions in (2, 3):
            points = [SpatialPoint(str(index), tuple(generator.randrange(-10, 11) for _ in range(dimensions)))
                      for index in range(150)]
            tree = KDTree(points[:75], dimensions)
            for point in points[75:]:
                tree.insert(point)
            generator.shuffle(points)
            while points:
                query = tuple(generator.uniform(-12, 12) for _ in range(dimensions))
                self._check_nearest(tree, points, query)
                lower, upper = (-4,) * dimensions, (5,) * dimensions
                expected = [point for point in points if all(-4 <= value <= 5 for value in point.coordinates)]
                self.assertEqual({point.identifier for point in tree.range_search(lower, upper)},
                                 {point.identifier for point in expected})
                self._check_nearest(tree, expected, query, lower, upper)
                removed = points.pop()
                self.assertEqual(tree.remove(removed.identifier), removed)
                self.assertEqual(len(tree), len(points))
            self.assertIsNone(tree.nearest((0,) * dimensions))

    def _check_nearest(self, tree: KDTree, points: list[SpatialPoint], query: tuple[float, ...],
                       *bounds: tuple[float, ...]) -> None:
        """Проверить точку и расстояние по независимому эталону."""
        actual = tree.nearest(query, *bounds)
        if not points:
            self.assertIsNone(actual)
            return
        expected = min(points, key=lambda point: (math.dist(query, point.coordinates), point.identifier))
        self.assertIsNotNone(actual)
        self.assertEqual(actual[0], expected)
        self.assertAlmostEqual(actual[1], math.dist(query, expected.coordinates))

    def test_duplicates_and_boundaries(self) -> None:
        """Сохранить разные ID в одинаковых координатах, включая границы диапазона."""
        tree = KDTree()
        for index in range(100):
            tree.insert(SpatialPoint(f"{index:03}", (1, 1)))
        self.assertEqual(tree.size, 100)
        self.assertEqual(tree.dimensions, 2)
        self.assertEqual(len(tree.range_search((1, 1), (1, 1))), 100)
        self.assertEqual(tree.nearest((1, 1))[0].identifier, "000")
        for index in range(100):
            tree.remove(f"{index:03}")
        self.assertEqual(tree.size, 0)
        self.assertIsNone(tree.nearest((1, 1)))

    def test_ordered_insertion(self) -> None:
        """Вставка упорядоченных данных не приводит к переполнению рекурсии."""
        tree = KDTree()
        for index in range(1200):
            tree.insert(SpatialPoint(str(index), (index, -index)))
        self.assertEqual(tree.nearest((500, -500))[0].identifier, "500")
        for index in range(0, 1200, 3):
            tree.remove(str(index))
        self.assertEqual(tree.size, 800)

    def test_invalid_inputs(self) -> None:
        """Отклонить неверные размерности, NaN, дубли ID и некорректные области."""
        tree = KDTree([SpatialPoint("a", (0, 0))])
        with self.assertRaises(ValueError):
            tree.insert(SpatialPoint("a", (1, 1)))
        with self.assertRaises(ValueError):
            tree.insert(SpatialPoint("b", (1, 2, 3)))
        with self.assertRaises(ValueError):
            tree.nearest((math.nan, 0))
        with self.assertRaises(ValueError):
            tree.nearest((0, 0), (0, 0))
        with self.assertRaises(ValueError):
            tree.range_search((2, 0), (1, 1))
        with self.assertRaises(KeyError):
            tree.remove("missing")
        self.assertEqual(tree.size, 1)
