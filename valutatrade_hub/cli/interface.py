"""Разбор команд и вывод результатов консольного приложения."""

import argparse
import shlex
import sys
from collections.abc import Callable, Sequence
from typing import Never

from prettytable import PrettyTable

from valutatrade_hub.core.currencies import supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    ValidationError,
    ValutaTradeError,
)
from valutatrade_hub.core.usecases import TradeResult, TradingService
from valutatrade_hub.logging_config import configure_logging


class CommandParser(argparse.ArgumentParser):
    """Парсер аргументов с доменными ошибками вместо завершения процесса."""

    def error(self, message: str) -> Never:
        """Преобразует ошибку разбора команды в ValidationError."""
        raise ValidationError(f"Ошибка команды: {message}. Выполните help")


def build_parser() -> CommandParser:
    """Создаёт парсер команд кошелька, курсов и управления сессией."""
    parser = CommandParser(
        prog="valutatrade", description="Виртуальный валютный кошелёк"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (("register", "Регистрация"), ("login", "Вход")):
        subparser = commands.add_parser(command, help=help_text)
        subparser.add_argument("--username", required=True)
        subparser.add_argument("--password", required=True)
    portfolio = commands.add_parser("show-portfolio", help="Портфель и его стоимость")
    portfolio.add_argument("--base")
    deposit = commands.add_parser("deposit", help="Пополнить виртуальный USD-баланс")
    deposit.add_argument("--amount", type=float, required=True)
    for command in ("buy", "sell"):
        subparser = commands.add_parser(
            command, help="Купить" if command == "buy" else "Продать"
        )
        subparser.add_argument("--currency", required=True)
        subparser.add_argument("--amount", type=float, required=True)
    rate = commands.add_parser("get-rate", help="Курс между двумя валютами")
    rate.add_argument("--from", dest="from_code", required=True)
    rate.add_argument("--to", dest="to_code", required=True)
    update = commands.add_parser("update-rates", help="Обновить курсы через API")
    update.add_argument("--source", choices=("coingecko", "exchangerate"))
    show = commands.add_parser("show-rates", help="Показать локальный кеш курсов")
    show.add_argument("--currency")
    show.add_argument("--top", type=int)
    show.add_argument("--base", default="USD")
    commands.add_parser("logout", help="Завершить сессию")
    commands.add_parser("exit", help="Закрыть приложение")
    help_parser = commands.add_parser("help", help="Список команд или справка команды")
    help_parser.add_argument("topic", nargs="?")
    return parser


class Console:
    """Консольный интерфейс торгового сервиса с интерактивной сессией."""

    def __init__(
        self,
        service: TradingService | None = None,
        output: Callable[[str], None] = print,
    ) -> None:
        """Подключает торговый сервис, функцию вывода и парсер команд."""
        self.service = service or TradingService()
        self.output = output
        self.parser = build_parser()
        self.should_exit = False

    def execute(self, command: str | Sequence[str]) -> int:
        """Выполняет команду и возвращает её код завершения.

        Строка разбирается через shlex; последовательность передаётся парсеру
        как готовые аргументы. Ошибки команды и домена выводятся пользователю
        с кодом 2, не прерывая интерактивную сессию.
        """
        try:
            tokens = shlex.split(command) if isinstance(command, str) else list(command)
            if not tokens:
                return 0
            args = self.parser.parse_args(tokens)
            self._dispatch(args)
            return 0
        except CurrencyNotFoundError as error:
            self.output(f"{error}. Поддерживаются: {', '.join(supported_codes())}")
        except ApiRequestError as error:
            self.output(f"{error}. Проверьте сеть и повторите update-rates позже")
        except (ValutaTradeError, ValueError) as error:
            self.output(str(error))
        except SystemExit as error:
            return int(error.code or 0)
        return 2

    def _dispatch(self, args: argparse.Namespace) -> None:
        """Вызывает сценарий команды и форматирует его результат."""
        match args.command:
            case "register":
                user = self.service.register(args.username, args.password)
                self.output(
                    f"Пользователь '{user.username}' зарегистрирован "
                    f"(id={user.user_id}). "
                    "Войдите: login --username "
                    + shlex.quote(user.username)
                    + " --password ****"
                )
            case "login":
                user = self.service.login(args.username, args.password)
                self.output(f"Вы вошли как '{user.username}'")
            case "logout":
                self.service.logout()
                self.output("Сессия завершена")
            case "deposit":
                deposit = self.service.deposit(args.amount)
                self.output(
                    f"Виртуальный баланс пополнен: {deposit.amount:,.2f} USD. "
                    f"Баланс: {deposit.after:,.2f} USD"
                )
            case "buy" | "sell":
                operation = (
                    self.service.buy if args.command == "buy" else self.service.sell
                )
                self._show_trade(operation(args.currency, args.amount), args.command)
            case "show-portfolio":
                view = self.service.show_portfolio(args.base)
                self.output(
                    f"Портфель пользователя '{view.username}' (база: {view.base}):"
                )
                if not view.rows:
                    self.output(
                        "Портфель пуст. Пополните виртуальный баланс: "
                        "deposit --amount 10000"
                    )
                else:
                    table = PrettyTable(["Валюта", "Баланс", f"Стоимость, {view.base}"])
                    for row in view.rows:
                        table.add_row(
                            [
                                row.currency_code,
                                f"{row.balance:.8f}",
                                f"{row.value:,.2f}",
                            ]
                        )
                    self.output(str(table))
                self.output(f"ИТОГО: {view.total:,.2f} {view.base}")
            case "get-rate":
                quote = self.service.get_rate(args.from_code, args.to_code)
                self.output(
                    f"Курс {args.from_code.upper()}→{args.to_code.upper()}: "
                    f"{quote.rate:.8f} (обновлено: {quote.updated_at})"
                )
                self.output(
                    f"Обратный курс {args.to_code.upper()}→{args.from_code.upper()}: "
                    f"{1.0 / quote.rate:.8f}"
                )
            case "update-rates":
                result = self.service.update_rates(args.source)
                self.output(
                    f"Обновлено курсов: {result.updated_count}. "
                    f"Последнее обновление: {result.last_refresh}"
                )
                for source, error in result.errors.items():
                    self.output(f"Источник {source} недоступен: {error}")
                if result.errors:
                    self.output(
                        "Обновление завершено с ошибками. Подробности: logs/parser.log"
                    )
            case "show-rates":
                rows = self.service.show_rates(args.currency, args.top, args.base)
                table = PrettyTable(
                    ["Пара", "Курс", "Обновлено", "Источник", "Состояние"]
                )
                for rate_row in rows:
                    table.add_row(
                        [
                            f"{rate_row.currency_code}_{rate_row.base}",
                            f"{rate_row.quote.rate:.8f}",
                            rate_row.quote.updated_at,
                            rate_row.quote.source,
                            "устарел" if rate_row.stale else "свежий",
                        ]
                    )
                self.output(str(table))
                if any(row.stale for row in rows):
                    self.output("Есть устаревшие курсы. Выполните update-rates")
            case "help":
                tokens = [args.topic, "--help"] if args.topic else ["--help"]
                self.parser.parse_args(tokens)
            case "exit":
                self.should_exit = True

    def _show_trade(self, result: TradeResult, action: str) -> None:
        """Выводит количество валюты, курс и изменения балансов сделки."""
        title = "Покупка выполнена" if action == "buy" else "Продажа выполнена"
        value_title = (
            "Оценочная стоимость покупки" if action == "buy" else "Оценочная выручка"
        )
        self.output(
            f"{title}: {result.amount:.4f} {result.currency_code} "
            f"по курсу {result.rate:.2f} USD/{result.currency_code}"
        )
        self.output(
            f"{result.currency_code}: было {result.before:.4f} "
            f"→ стало {result.after:.4f}"
        )
        self.output(
            f"USD: было {result.usd_before:,.2f} → стало {result.usd_after:,.2f}"
        )
        self.output(f"{value_title}: {result.usd_value:,.2f} USD")

    def run(self) -> int:
        """Читает команды до exit, конца ввода или прерывания с клавиатуры."""
        self.output(
            "ValutaTrade Hub. Выполните help для списка команд, exit для выхода."
        )
        while not self.should_exit:
            try:
                command = input("valutatrade> ")
            except EOFError:
                self.output("")
                break
            except KeyboardInterrupt:
                self.output("\nСессия завершена")
                break
            self.execute(command)
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Запускает отдельную команду либо интерактивную сессию приложения."""
    try:
        configure_logging()
        console = Console()
        arguments = list(sys.argv[1:] if argv is None else argv)
        return console.execute(arguments) if arguments else console.run()
    except (ValutaTradeError, OSError, ValueError) as error:
        print(f"Не удалось запустить приложение: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
