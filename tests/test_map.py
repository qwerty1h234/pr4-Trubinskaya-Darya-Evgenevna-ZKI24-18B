"""Проверки загрузчика, евклидовой метрики, кэша и HTTP-интерфейса."""

from contextlib import closing
from http.client import HTTPConnection
import io
import json
from threading import Thread
from typing import Any
import unittest
from unittest.mock import patch

from nearest_map.addresses import resolve_address
from nearest_map.models import Area, Coordinates, MapObject
from nearest_map.osm import MapDataError, build_query, load_objects, parse_objects
from nearest_map.server import MapServer
from nearest_map.service import MapService


def request_data() -> dict[str, Any]:
    """Подготовить запрос небольшой области около точки (0, 0)."""
    return {"point": {"lat": 0, "lon": 0}, "category": "cafe",
            "area": {"south": -0.01, "west": -0.01, "north": 0.01, "east": 0.01}}


def objects(_area: Area, category: str) -> list[MapObject]:
    """Вернуть фиксированные объекты для проверки без сети."""
    return [MapObject("node/1", "Кафе", "Улица, 1", category, Coordinates(0.001, 0)),
            MapObject("node/2", "Кафе 2", "Улица, 2", category, Coordinates(0.009, 0)),
            MapObject("node/3", "За областью", "Улица, 3", category, Coordinates(0.02, 0))]


class MapTests(unittest.TestCase):
    """Проверки бизнес-логики без обращения к публичным серверам."""

    def test_nearest_and_cache(self) -> None:
        """Выдать ближайший объект в области и повторно использовать кэш."""
        with patch("tests.test_map.objects", wraps=objects) as loader:
            service = MapService(loader)
            payload = request_data()
            result = service.search(payload)
            self.assertEqual(result["nearest"]["id"], "node/1")
            self.assertEqual(result["count"], 2)
            self.assertAlmostEqual(result["nearest"]["distance_m"], 111.19, places=2)
            self.assertFalse(result["cached"])
            self.assertTrue(service.search(payload)["cached"])
            self.assertEqual(loader.call_count, 1)
            payload["refresh"] = True
            service.search(payload)
            self.assertEqual(loader.call_count, 2)
            service.clear_cache()
            payload["refresh"] = False
            self.assertFalse(service.search(payload)["cached"])

    def test_empty_and_bad_requests(self) -> None:
        """Обработать пустой результат и отклонить запросы за пределами области."""
        service = MapService(lambda _area, _category: [])
        result = service.search(request_data())
        self.assertIsNone(result["nearest"])
        self.assertEqual(result["objects"], [])
        for payload in ({}, [], {**request_data(), "category": "unknown"},
                        {**request_data(), "point": {"lat": 0.1, "lon": 0}}):
            with self.assertRaises(ValueError):
                service.search(payload)
        with self.assertRaises(ValueError):
            Area(-1, -1, 1, 1)

    def test_osm_parsing(self) -> None:
        """Читать координаты узлов, центры площадей, адреса и исключать чужие категории."""
        area = Area(-0.01, -0.01, 0.01, 0.01)
        elements = [
            {"type": "node", "id": 1, "lat": 0, "lon": 0,
             "tags": {"amenity": "cafe", "name": "Кофе", "addr:street": "Улица", "addr:housenumber": "7"}},
            {"type": "way", "id": 2, "center": {"lat": 0.001, "lon": 0}, "tags": {"amenity": "cafe"}},
            {"type": "node", "id": 3, "lat": 0, "lon": 0, "tags": {"amenity": "atm"}},
            {"type": "node", "id": 4, "lat": 1, "lon": 0, "tags": {"amenity": "cafe"}},
        ]
        result = parse_objects({"elements": elements}, area, "cafe")
        self.assertEqual([item.identifier for item in result], ["node/1", "way/2"])
        self.assertEqual(result[0].address, "Улица, 7")
        self.assertIn("не указан", result[1].address)
        self.assertIn('nwr["amenity"="cafe"]', build_query(area, "cafe"))
        self.assertIn("out center", build_query(area, "cafe"))

    def test_network_errors_and_incomplete_data(self) -> None:
        """Сетевой сбой не превращается в ложный ответ об отсутствии объектов."""
        area = Area(-0.01, -0.01, 0.01, 0.01)
        with patch("nearest_map.osm.urlopen", side_effect=TimeoutError):
            with self.assertRaises(MapDataError):
                load_objects(area, "cafe")
        bad = json.dumps({"elements": [], "remark": "timeout"}).encode()
        with patch("nearest_map.osm.urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(bad)):
            with patch("nearest_map.osm._map_download", side_effect=MapDataError("API недоступен")):
                with self.assertRaises(MapDataError):
                    load_objects(area, "cafe")

    def test_main_api_fallback(self) -> None:
        """При отказе Overpass прочитать геометрию из основного API OSM."""
        data = {"elements": [
            {"type": "node", "id": 1, "lat": 0, "lon": 0},
            {"type": "node", "id": 2, "lat": 0.002, "lon": 0.002},
            {"type": "way", "id": 3, "nodes": [1, 2], "tags": {"amenity": "cafe"}},
        ]}
        responses = [TimeoutError(), TimeoutError(), io.BytesIO(json.dumps(data).encode())]
        with patch("nearest_map.osm.urlopen", side_effect=responses):
            found = load_objects(Area(-0.01, -0.01, 0.01, 0.01), "cafe")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].location, Coordinates(0.001, 0.001))

    def test_address_lookup(self) -> None:
        """Уточнить адрес по ID объекта, сохранив явное отсутствие при сбое."""
        item = MapObject("node/987654321", "Кафе", "Адрес не указан в OpenStreetMap", "cafe", Coordinates(0, 0))
        data = [{"osm_type": "node", "osm_id": 987654321,
                 "address": {"city": "Город", "road": "Улица", "house_number": "9"}}]
        with patch("nearest_map.addresses.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            with patch("nearest_map.addresses.sleep"):
                self.assertEqual(resolve_address(item), "Город, Улица, 9")
        unavailable = MapObject("node/987654322", "Кафе", item.address, "cafe", item.location)
        with patch("nearest_map.addresses.urlopen", side_effect=OSError):
            with patch("nearest_map.addresses.sleep"):
                self.assertEqual(resolve_address(unavailable), item.address)


class ServerTests(unittest.TestCase):
    """Проверить настоящий локальный HTTP-сервер без внешних запросов."""

    def setUp(self) -> None:
        """Запустить сервер на свободном порту."""
        self.server = MapServer(("127.0.0.1", 0), MapService(objects))
        self.worker = Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self) -> None:
        """Закрыть сокет и дождаться завершения серверного потока."""
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    def test_static_files_and_categories(self) -> None:
        """Получить все ресурсы страницы и список категорий."""
        for path in ("/", "/app.js", "/style.css", "/vendor/leaflet.js", "/vendor/leaflet.css", "/api/categories"):
            with closing(HTTPConnection(*self.server.server_address, timeout=5)) as connection:
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_search_and_validation(self) -> None:
        """Отправить JSON через HTTP и проверить успешный и ошибочный запросы."""
        for payload, expected in ((request_data(), 200), ({}, 400)):
            with closing(HTTPConnection(*self.server.server_address, timeout=5)) as connection:
                connection.request("POST", "/api/search", body=json.dumps(payload),
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                result = json.loads(response.read())
                self.assertIn("nearest" if expected == 200 else "error", result)
