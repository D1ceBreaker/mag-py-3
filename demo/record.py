"""Воспроизводимая запись демонстрации с искусственными ответами API."""

import json
import logging
import os
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from valutatrade_hub.cli.interface import Console
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging

DEMO_TIME = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
DEMO_TIMESTAMP = "2026-11-07T12:00:00Z"
INTRO = "Демонстрация: искусственные ответы CoinGecko и ExchangeRate-API, без сети."
COMMANDS: tuple[tuple[str, int, str], ...] = (
    ("update-rates", 0, "Обновлено курсов: 6"),
    ("show-rates --top 2", 0, "BTC_USD"),
    ("register --username alice --password demo1234", 0, "зарегистрирован"),
    ("login --username alice --password demo1234", 0, "Вы вошли"),
    ("show-portfolio", 0, "Портфель пуст"),
    ("deposit --amount 10000", 0, "Виртуальный баланс пополнен"),
    ("buy --currency BTC --amount 0.05", 0, "Покупка выполнена"),
    ("sell --currency BTC --amount 0.01", 0, "Продажа выполнена"),
    ("show-portfolio", 0, "ИТОГО"),
    ("get-rate --from USD --to BTC", 0, "Обратный курс"),
    ("show-rates --currency RUB", 0, "RUB_USD"),
    ("show-rates --base EUR", 0, "BTC_EUR"),
    ("sell --currency BTC --amount 100", 2, "Недостаточно средств"),
    ("get-rate --from ABC --to USD", 2, "Неизвестная валюта"),
    ("buy --currency ETH --amount nan", 2, "положительным числом"),
    ("logout", 0, "Сессия завершена"),
)


class DemoResponse:
    """Ответ API с заранее заданным JSON для демонстрации."""

    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        """Сохраняет данные искусственного JSON-ответа."""
        self.payload = payload

    def json(self) -> dict[str, object]:
        """Возвращает заданные данные ответа API."""
        return self.payload


def demo_get(
    url: str,
    *,
    params: dict[str, str] | None,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> DemoResponse:
    """Возвращает искусственный ответ для известного URL внешнего API."""
    if url.startswith("https://api.coingecko.com/"):
        return DemoResponse(
            {
                "bitcoin": {"usd": 59337.21},
                "ethereum": {"usd": 3720.0},
                "solana": {"usd": 145.12},
            }
        )
    if url.startswith("https://v6.exchangerate-api.com/v6/demo-key/"):
        return DemoResponse(
            {
                "result": "success",
                "base_code": "USD",
                "conversion_rates": {
                    "USD": 1.0,
                    "EUR": 0.927,
                    "GBP": 0.809,
                    "RUB": 98.45,
                },
            }
        )
    raise AssertionError(f"Неожиданный API-запрос: {url}")


def close_loggers() -> None:
    """Удаляет и закрывает обработчики логов демонстрационного процесса."""
    for name in ("valutatrade.actions", "valutatrade.parser"):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


def run_commands() -> list[str]:
    """Выполняет сценарий демонстрации и собирает команды с их выводом."""
    events = [INTRO + "\n"]
    console = Console()
    for command, expected_status, expected_text in COMMANDS:
        output = StringIO()
        with redirect_stdout(output):
            status = console.execute(command)
        result = output.getvalue()
        if status != expected_status or expected_text not in result:
            raise RuntimeError(
                f"Команда {command!r}: код {status}, ожидалось {expected_status}; "
                f"вывод {result!r}"
            )
        events.append(f"valutatrade> {command}\n{result}")
    return events


def record() -> tuple[Path, Path]:
    """Создаёт Asciinema-запись и транскрипт на искусственных курсах.

    Использует временное хранилище и подменяет HTTP-запросы. Возвращает пути
    к session.cast и session.txt в каталоге сценария.
    """
    directory = Path(__file__).resolve().parent
    settings = SettingsLoader()
    with tempfile.TemporaryDirectory(prefix="valutatrade-demo-") as temporary:
        environment = {
            "VALUTATRADE_DATA_DIR": str(Path(temporary) / "data"),
            "VALUTATRADE_LOG_DIR": str(Path(temporary) / "logs"),
            "EXCHANGERATE_API_KEY": "demo-key",
        }
        with (
            patch.dict(os.environ, environment),
            patch("requests.get", side_effect=demo_get),
            patch(
                "valutatrade_hub.parser_service.updater.iso_utc",
                return_value=DEMO_TIMESTAMP,
            ),
            patch("valutatrade_hub.core.rates.utc_now", return_value=DEMO_TIME),
        ):
            settings.reload()
            try:
                configure_logging()
                events = run_commands()
            finally:
                close_loggers()
    settings.reload()
    cast_path = directory / "session.cast"
    text_path = directory / "session.txt"
    cast_header = {
        "version": 2,
        "width": 120,
        "height": 35,
        "timestamp": int(DEMO_TIME.timestamp()),
        "env": {"SHELL": "/bin/sh", "TERM": "xterm-256color"},
    }
    cast_lines = [json.dumps(cast_header, ensure_ascii=False)]
    for index, event in enumerate(events):
        cast_lines.append(
            json.dumps(
                [float(index), "o", event.replace("\n", "\r\n")], ensure_ascii=False
            )
        )
    cast_path.write_text("\n".join(cast_lines) + "\n", encoding="utf-8")
    text_path.write_text("\n".join(events), encoding="utf-8")
    return cast_path, text_path


def main() -> None:
    """Создаёт демонстрационные файлы и печатает пути к ним."""
    cast_path, text_path = record()
    print(f"Создано: {cast_path}")
    print(f"Создано: {text_path}")


if __name__ == "__main__":
    main()
