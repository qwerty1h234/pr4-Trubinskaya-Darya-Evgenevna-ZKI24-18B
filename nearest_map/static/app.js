"use strict";

const byId = (id) => document.getElementById(id);
const statusLine = byId("status");
function status(message, error = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", error);
}

async function initialize() {
  if (!window.L) {
    status("Не удалось загрузить библиотеку карты. Проверьте комплект файлов приложения.", true);
    return;
  }
  const map = L.map("map", { preferCanvas: true, maxBounds: [[-85, -180], [85, 180]], maxBoundsViscosity: 1 });
  map.setView([55.752500, 37.611500], 17);
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    minZoom: 4, maxZoom: 19, noWrap: true
  }).addTo(map);
  let tileWarning = false;
  tiles.on("tileerror", () => {
    if (!tileWarning) {
      tileWarning = true;
      status("Карта недоступна: проверьте интернет. Координаты точки можно ввести вручную.", true);
    }
  });
  const objectsLayer = L.layerGroup().addTo(map);
  const resultLayer = L.layerGroup().addTo(map);
  let point = { lat: 55.752500, lon: 37.611500 };
  let area;
  let rectangle;
  let generation = 0;
  let controller = null;
  const marker = L.circleMarker([point.lat, point.lon], {
    radius: 8, color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1
  }).addTo(map).bindTooltip("Точка поиска");

  function resetResult() {
    generation += 1;
    if (controller) controller.abort();
    controller = null;
    byId("search").disabled = false;
    objectsLayer.clearLayers();
    resultLayer.clearLayers();
    byId("result").hidden = true;
  }

  function readPoint() {
    const lat = Number(byId("latitude").value);
    const lon = Number(byId("longitude").value);
    if (!byId("latitude").value || !byId("longitude").value || !Number.isFinite(lat) || !Number.isFinite(lon)
        || Math.abs(lat) > 85 || Math.abs(lon) > 180) {
      throw new Error("Введите широту от −85 до 85 и долготу от −180 до 180.");
    }
    return { lat, lon };
  }

  function selectPoint(value, pan) {
    resetResult();
    point = value;
    byId("latitude").value = point.lat.toFixed(6);
    byId("longitude").value = point.lon.toFixed(6);
    marker.setLatLng([point.lat, point.lon]);
    if (pan) map.panTo([point.lat, point.lon]);
    status("Точка выбрана. Убедитесь, что она внутри выделенной области, и запустите поиск.");
  }

  function selectArea() {
    resetResult();
    const bounds = map.getBounds();
    area = { south: Math.max(-85, bounds.getSouth()), west: Math.max(-180, bounds.getWest()),
      north: Math.min(85, bounds.getNorth()), east: Math.min(180, bounds.getEast()) };
    if (rectangle) map.removeLayer(rectangle);
    rectangle = L.rectangle([[area.south, area.west], [area.north, area.east]], {
      color: "#2563eb", weight: 2, fillOpacity: 0.035, interactive: false
    }).addTo(map);
    byId("area-description").textContent = `Юг ${area.south.toFixed(4)}, север ${area.north.toFixed(4)}; ` +
      `запад ${area.west.toFixed(4)}, восток ${area.east.toFixed(4)}. Максимум 40 км по стороне.`;
    status("Область выделена. Выберите тип объекта и нажмите «Найти».");
  }

  function popup(item) {
    const box = document.createElement("div");
    const title = document.createElement("div");
    title.className = "popup-title";
    title.textContent = item.name;
    const address = document.createElement("div");
    address.textContent = item.address;
    box.append(title, address);
    return box;
  }

  function showResult(data) {
    for (const item of data.objects) {
      L.circleMarker([item.lat, item.lon], {
        radius: 5, color: "#475569", weight: 1, fillColor: "#94a3b8", fillOpacity: 0.8, bubblingMouseEvents: false
      }).bindPopup(popup(item)).addTo(objectsLayer);
    }
    if (!data.nearest) {
      status("В выбранной области объекты этого типа не найдены. Выберите другую область или тип.");
      return;
    }
    const item = data.nearest;
    const nearest = L.circleMarker([item.lat, item.lon], {
      radius: 9, color: "#fff", weight: 2, fillColor: "#dc2626", fillOpacity: 1, bubblingMouseEvents: false
    }).bindPopup(popup(item)).addTo(resultLayer);
    L.polyline([[point.lat, point.lon], [item.lat, item.lon]], {
      color: "#dc2626", weight: 2, dashArray: "6 5"
    }).addTo(resultLayer);
    byId("object-name").textContent = item.name;
    byId("object-address").textContent = item.address;
    byId("object-distance").textContent = `Расстояние по прямой: ${item.distance_m.toLocaleString("ru-RU")} м`;
    byId("object-link").href = item.url;
    byId("result").hidden = false;
    status(`В области: ${data.count} объектов. Ближайший найден через k-d дерево.` +
      (data.cached ? " Использованы данные из кэша (до 5 минут)." : " Данные загружены из OpenStreetMap."));
    nearest.openPopup();
  }

  map.on("click", (event) => selectPoint({ lat: event.latlng.lat, lon: event.latlng.lng }, false));
  byId("set-point").addEventListener("click", () => {
    try { selectPoint(readPoint(), true); } catch (error) { status(error.message, true); }
  });
  byId("set-area").addEventListener("click", selectArea);
  byId("category").addEventListener("change", () => { resetResult(); status("Тип выбран. Нажмите «Найти»."); });
  for (const id of ["latitude", "longitude"]) byId(id).addEventListener("input", resetResult);
  byId("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      point = readPoint();
      marker.setLatLng([point.lat, point.lon]);
    } catch (error) { status(error.message, true); return; }
    resetResult();
    const requestGeneration = generation;
    controller = new AbortController();
    const currentController = controller;
    const timer = setTimeout(() => currentController.abort(), 65000);
    byId("search").disabled = true;
    status("Загрузка объектов и построение k-d дерева… Запрос может занять до минуты.");
    try {
      const response = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ point, area, category: byId("category").value, refresh: byId("refresh").checked }),
        signal: currentController.signal });
      const data = await response.json();
      if (requestGeneration !== generation) return;
      if (!response.ok) throw new Error(data.error || "Не удалось выполнить поиск.");
      showResult(data);
    } catch (error) {
      if (requestGeneration === generation) {
        status(error.name === "AbortError" ? "Время ожидания истекло. Попробуйте меньшую область." : error.message, true);
      }
    } finally {
      clearTimeout(timer);
      if (requestGeneration === generation) { byId("search").disabled = false; controller = null; }
    }
  });
  selectArea();
  try {
    const response = await fetch("/api/categories");
    if (!response.ok) throw new Error("Не удалось загрузить типы объектов.");
    const data = await response.json();
    byId("category").replaceChildren();
    for (const item of data.categories) byId("category").add(new Option(item.label, item.id));
  } catch (error) { status(error.message, true); byId("search").disabled = true; }
}

initialize().catch((error) => status(`Ошибка запуска: ${error.message}`, true));
