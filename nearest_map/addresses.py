"""Уточнение адреса объекта через Nominatim по его идентификатору OSM."""

from collections import OrderedDict, deque
import json
from threading import Lock
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import MapObject

_LOCK = Lock()
_TIMES: deque[float] = deque([0.0], maxlen=1)
_CACHE: OrderedDict[str, str] = OrderedDict()
UNKNOWN_ADDRESS = "Адрес не указан в OpenStreetMap"


def _lookup(identifier: str) -> str | None:
    """Запросить адрес именно объекта по ID, не подменяя его ближайшим зданием."""
    kind, number = identifier.split("/")
    query = urlencode({"osm_ids": {"node": "N", "way": "W", "relation": "R"}[kind] + number,
                       "format": "jsonv2", "addressdetails": 1})
    request = Request("https://nominatim.openstreetmap.org/lookup?" + query,
                      headers={"User-Agent": "NearestMap/1.0 (OpenStreetMap educational application)",
                               "Accept": "application/json", "Accept-Language": "ru"})
    with urlopen(request, timeout=8) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        return None
    data = json.loads(raw)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    if data[0].get("osm_type") != kind or data[0].get("osm_id") != int(number):
        return None
    address = data[0].get("address", {})
    if not isinstance(address, dict):
        return None
    street = address.get("road") or address.get("pedestrian") or address.get("square")
    city = address.get("city") or address.get("town") or address.get("village")
    parts = [city, street, address.get("house_number")]
    return ", ".join(str(part) for part in parts if part) if street else None


def resolve_address(item: MapObject) -> str:
    """Уточнить отсутствующий адрес; ограничить частоту одним запросом в секунду."""
    if item.address != UNKNOWN_ADDRESS:
        return item.address
    with _LOCK:
        if item.identifier in _CACHE:
            _CACHE.move_to_end(item.identifier)
            return _CACHE[item.identifier]
        sleep(max(0, 1 - (monotonic() - _TIMES[-1])))
        _TIMES.append(monotonic())
        try:
            address = _lookup(item.identifier)
        except (OSError, URLError, ValueError, KeyError):
            return item.address
        if address:
            _CACHE[item.identifier] = address
            if len(_CACHE) > 128:
                _CACHE.popitem(last=False)
            return address
    return item.address
