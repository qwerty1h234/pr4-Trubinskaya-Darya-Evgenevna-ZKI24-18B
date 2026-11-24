"""Локальный HTTP-сервер интерактивной карты и поискового API."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import CATEGORIES
from .osm import MapDataError
from .service import MapService

STATIC = Path(__file__).with_name("static")
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript; charset=utf-8"),
    "/vendor/leaflet.css": ("vendor/leaflet.css", "text/css; charset=utf-8"),
}


class MapServer(ThreadingHTTPServer):
    """HTTP-сервер с общим сервисом поиска для обработчиков запросов."""

    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def __init__(self, address: tuple[str, int], service: MapService | None = None) -> None:
        """Привязать сокет и источник данных карты."""
        self.service = service if service is not None else MapService()
        super().__init__(address, MapHandler)


class MapHandler(BaseHTTPRequestHandler):
    """Выдача статических ресурсов и обработка JSON-запросов поиска."""

    server: MapServer
    server_version = "NearestMap/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
        """Не выводить служебные запросы браузера в консоль приложения."""

    def _send(self, status: int, content: bytes, content_type: str) -> None:
        """Отправить ответ с точной длиной и типом содержимого."""
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, data: dict[str, Any]) -> None:
        """Отправить UTF-8 JSON без нечисловых NaN/Infinity."""
        self._send(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Выдать страницу карты, её ресурсы или список типов объектов."""
        path = urlsplit(self.path).path
        if path == "/api/categories":
            self._json(200, {"categories": [{"id": key, "label": value[0]} for key, value in CATEGORIES.items()]})
        elif path in FILES:
            filename, content_type = FILES[path]
            self._send(200, (STATIC / filename).read_bytes(), content_type)
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "Страница не найдена."})

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        """Выполнить ограниченный по размеру JSON-запрос поиска."""
        if urlsplit(self.path).path != "/api/search":
            self._json(404, {"error": "Неизвестный адрес запроса."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                self._json(413, {"error": "Недопустимый размер запроса."})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(415, {"error": "Ожидается application/json."})
                return
            payload = json.loads(self.rfile.read(length))
            result = self.server.service.search(payload)
        except (ValueError, TypeError, OverflowError) as error:
            self._json(400, {"error": str(error)})
        except MapDataError as error:
            self._json(503, {"error": str(error)})
        else:
            self._json(200, result)
