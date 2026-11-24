"""Запуск приложения командой python -m nearest_map."""

import argparse
import sys
import webbrowser

from .server import MapServer


def _port(value: str) -> int:
    """Проверить номер TCP-порта; ноль позволяет системе выбрать свободный порт."""
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Port must be an integer") from error
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 0 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    """Запустить локальный сервер и открыть карту в браузере."""
    parser = argparse.ArgumentParser(description="Nearest OpenStreetMap object using a k-d tree.")
    parser.add_argument("--port", type=_port, default=8765, help="local port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="print URL without opening a browser")
    options = parser.parse_args(argv)
    try:
        server = MapServer(("127.0.0.1", options.port))
    except OSError as error:
        print(f"Не удалось запустить сервер: {error}. Выберите другой порт через --port.", file=sys.stderr)
        return 1
    with server:
        address = f"http://127.0.0.1:{server.server_address[1]}"
        print(f"Карта: {address}\nОстановка: Ctrl+C", flush=True)
        if not options.no_browser:
            try:
                webbrowser.open(address)
            except webbrowser.Error:
                print("Откройте указанный адрес вручную.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
