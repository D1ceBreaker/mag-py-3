import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from valutatrade_hub.cli.interface import Console
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.core.utils import iso_utc
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class ConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "VALUTATRADE_DATA_DIR": self.directory.name,
                "VALUTATRADE_LOG_DIR": self.directory.name + "/logs",
            },
        )
        self.environment.start()
        SettingsLoader().reload()
        self.database = DatabaseManager()
        timestamp = iso_utc()
        self.database.write(
            "rates.json",
            {
                "pairs": {
                    "BTC_USD": {
                        "rate": 50_000.0,
                        "updated_at": timestamp,
                        "source": "test",
                    }
                },
                "last_refresh": timestamp,
            },
        )
        self.lines: list[str] = []
        self.console = Console(TradingService(), self.lines.append)

    def tearDown(self) -> None:
        self.environment.stop()
        SettingsLoader().reload()
        self.directory.cleanup()

    def test_complete_cycle_with_quoted_username(self) -> None:
        commands = (
            'register --username "Alice Smith" --password "pass word"',
            'login --username "Alice Smith" --password "pass word"',
            "deposit --amount 10000",
            "buy --currency btc --amount 0.05",
            "sell --currency BTC --amount 0.01",
            "show-portfolio",
            "get-rate --from USD --to BTC",
            "show-rates --top 1",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.console.execute(command), 0)
        output = "\n".join(self.lines)
        self.assertIn("Вы вошли как 'Alice Smith'", output)
        self.assertIn("Покупка выполнена", output)
        self.assertIn("Продажа выполнена", output)
        self.assertIn("ИТОГО: 10,000.00 USD", output)
        self.assertIn("Курс USD→BTC: 0.00002000", output)

    def test_invalid_commands_do_not_stop_console(self) -> None:
        for command in (
            "buy --amount bad --currency BTC",
            "buy --currency BTC",
            "register --username alice --password 'unterminated",
            "unknown-command",
            "get-rate --from ABC --to USD",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.console.execute(command), 2)
        self.assertFalse(self.console.should_exit)
        self.assertEqual(self.console.execute("exit"), 0)
        self.assertTrue(self.console.should_exit)

    def test_help_keeps_interactive_session_running(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(self.console.execute("help buy"), 0)
        self.assertIn("--currency", output.getvalue())
        self.assertFalse(self.console.should_exit)

    def test_cli_errors_are_friendly(self) -> None:
        self.assertEqual(self.console.execute("show-portfolio"), 2)
        self.assertIn("Сначала выполните login", self.lines[-1])
        self.assertEqual(self.console.execute("get-rate --from ABC --to USD"), 2)
        self.assertIn("Поддерживаются", self.lines[-1])

    def test_installed_module_accepts_piped_repl(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "valutatrade_hub"],
            input=(
                "register --username alice --password 1234\n"
                "login --username alice --password 1234\n"
                "deposit --amount 1000\n"
                "buy --currency BTC --amount 0.01\n"
                "show-portfolio\n"
                "sell --currency BTC --amount 100\n"
                "exit\n"
            ),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("ИТОГО: 1,000.00 USD", completed.stdout)
        self.assertIn("Недостаточно средств", completed.stdout)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
