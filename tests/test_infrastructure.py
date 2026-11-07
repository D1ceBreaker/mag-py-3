import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from valutatrade_hub.core.exceptions import InsufficientFundsError, StorageError
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.core.utils import iso_utc
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging


class InfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "VALUTATRADE_DATA_DIR": str(self.root / "data"),
                "VALUTATRADE_LOG_DIR": str(self.root / "logs"),
                "VALUTATRADE_RATES_TTL_SECONDS": "42",
            },
        )
        self.environment.start()
        SettingsLoader().reload()
        self.database = DatabaseManager()

    def tearDown(self) -> None:
        for name in ("actions", "parser"):
            logger = logging.getLogger(f"valutatrade.{name}")
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()
        self.environment.stop()
        SettingsLoader().reload()
        self.temporary.cleanup()

    def test_singletons_follow_reloaded_configuration(self) -> None:
        self.assertIs(SettingsLoader(), SettingsLoader())
        self.assertIs(self.database, DatabaseManager())
        self.assertEqual(SettingsLoader().rates_ttl_seconds, 42)
        self.assertEqual(
            SettingsLoader().path("users.json"),
            (self.root / "data/users.json").resolve(),
        )
        with patch.dict(
            os.environ,
            {
                "VALUTATRADE_DATA_DIR": str(self.root / "other"),
                "VALUTATRADE_RATES_TTL_SECONDS": "17",
            },
        ):
            SettingsLoader().reload()
            self.assertEqual(SettingsLoader().rates_ttl_seconds, 17)
            self.database.write("users.json", [])
            self.assertTrue((self.root / "other/users.json").exists())
        SettingsLoader().reload()
        self.assertEqual(SettingsLoader().rates_ttl_seconds, 42)

    def test_corrupt_json_fails_without_replacing_file(self) -> None:
        path = SettingsLoader().path("users.json")
        self.database.write("users.json", [])
        path.write_text("{broken", encoding="utf-8")

        with self.assertRaises(StorageError):
            self.database.read("users.json", [])

        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_failed_replace_preserves_original_and_cleans_temp(self) -> None:
        self.database.write("portfolios.json", [{"user_id": 1}])
        path = SettingsLoader().path("portfolios.json")
        before = path.read_bytes()

        with patch(
            "valutatrade_hub.infra.database.os.replace", side_effect=OSError("disk")
        ):
            with self.assertRaises(StorageError):
                self.database.write("portfolios.json", [{"user_id": 2}])

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_cross_process_transactions_preserve_all_updates(self) -> None:
        worker = "\n".join(
            (
                "import time",
                "from valutatrade_hub.infra.database import DatabaseManager",
                "database = DatabaseManager()",
                "for _ in range(10):",
                "    with database.transaction():",
                "        state = database.read('counter.json', {'count': 0})",
                "        time.sleep(0.005)",
                "        state['count'] += 1",
                "        database.write('counter.json', state)",
            )
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", worker],
                cwd=Path(__file__).resolve().parents[1],
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        try:
            for process in processes:
                _, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

        self.assertEqual(self.database.read("counter.json")["count"], 20)

    def test_trade_logs_success_and_error_without_password(self) -> None:
        configure_logging()
        service = TradingService(self.database)
        service.register("alice", "secret-pass")
        service.login("alice", "secret-pass")
        service.deposit(100.0)
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

        service.buy("btc", 0.001)
        with self.assertRaises(InsufficientFundsError):
            service.buy("BTC", 1.0)

        path = self.root / "logs/actions.log"
        content = path.read_text(encoding="utf-8")
        records = [json.loads(line) for line in content.splitlines()]
        buys = [record for record in records if record["action"] == "BUY"]
        self.assertEqual([record["result"] for record in buys], ["OK", "ERROR"])
        self.assertEqual(buys[0]["username"], "alice")
        self.assertEqual(buys[0]["currency_code"], "BTC")
        self.assertEqual(buys[0]["rate"], 50_000.0)
        self.assertEqual(buys[1]["error_type"], "InsufficientFundsError")
        self.assertNotIn("secret-pass", content)


if __name__ == "__main__":
    unittest.main()
