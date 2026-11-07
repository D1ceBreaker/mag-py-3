import argparse
import logging
import math
import sys
import time
from collections.abc import Sequence

from valutatrade_hub.core.exceptions import ValutaTradeError
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.updater import RatesUpdater

LOGGER = logging.getLogger("valutatrade.parser")


def main(argv: Sequence[str] | None = None) -> int:
    """Запускает парсер и возвращает код завершения процесса."""
    parser = argparse.ArgumentParser(prog="vth-parser")
    parser.add_argument("--interval", type=float, default=300.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--source", choices=("coingecko", "exchangerate"))
    arguments = parser.parse_args(argv)
    if not math.isfinite(arguments.interval) or arguments.interval <= 0:
        parser.error("--interval должен быть положительным числом")
    try:
        configure_logging()
        updater = RatesUpdater()
    except (ValutaTradeError, OSError, ValueError) as error:
        print(f"Не удалось запустить парсер: {error}", file=sys.stderr)
        return 2
    try:
        while True:
            try:
                result = updater.run_update(arguments.source)
                LOGGER.info(
                    "Цикл завершён: %s обновлено, %s ошибок",
                    result.updated_count,
                    len(result.errors),
                )
            except ValutaTradeError as error:
                LOGGER.error("Обновление не выполнено: %s", error)
                if arguments.once:
                    return 1
            if arguments.once:
                return 0
            time.sleep(arguments.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
