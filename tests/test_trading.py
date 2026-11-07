import math
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from valutatrade_hub.core.exceptions import (
    AuthenticationError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    RateUnavailableError,
    StorageError,
    ValidationError,
    WalletNotFoundError,
)
from valutatrade_hub.core.rates import RatesService
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.core.utils import iso_utc, utc_now
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class TradingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ, {"VALUTATRADE_DATA_DIR": self.directory.name}
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
                    },
                    "EUR_USD": {
                        "rate": 1.2,
                        "updated_at": timestamp,
                        "source": "test",
                    },
                },
                "last_refresh": timestamp,
            },
        )
        self.service = TradingService(
            self.database, RatesService(self.database, refresh=Mock())
        )

    def tearDown(self) -> None:
        self.environment.stop()
        SettingsLoader().reload()
        self.directory.cleanup()

    def _login(self) -> None:
        self.service.register("alice", "pass1234")
        self.service.login("alice", "pass1234")

    def _balances(self) -> dict[str, float]:
        portfolio = self.database.read("portfolios.json")[0]
        return {code: entry["balance"] for code, entry in portfolio["wallets"].items()}

    def test_registration_stores_salt_and_empty_portfolio(self) -> None:
        first = self.service.register("alice", "pass1234")
        second = self.service.register("bob", "pass1234")
        users = self.database.read("users.json")
        portfolios = self.database.read("portfolios.json")
        self.assertEqual((first.user_id, second.user_id), (1, 2))
        self.assertNotEqual(users[0]["salt"], users[1]["salt"])
        self.assertNotEqual(users[0]["hashed_password"], users[1]["hashed_password"])
        self.assertNotIn("pass1234", str(users))
        self.assertEqual(portfolios[0], {"user_id": 1, "wallets": {}})
        with self.assertRaises(ValidationError):
            self.service.register("alice", "other1234")
        self.assertEqual(len(self.database.read("users.json")), 2)

    def test_session_and_password_guards(self) -> None:
        self.service.register("alice", "pass1234")
        with self.assertRaises(AuthenticationError):
            self.service.show_portfolio()
        with self.assertRaises(AuthenticationError):
            self.service.deposit(10)
        with self.assertRaises(AuthenticationError):
            self.service.login("alice", "wrong")
        self.service.login("alice", "pass1234")
        self.assertEqual(self.service.show_portfolio().rows, [])
        self.service.logout()
        with self.assertRaises(AuthenticationError):
            self.service.buy("BTC", 0.01)

    def test_deposit_buy_sell_persist_both_balances_and_transactions(self) -> None:
        self._login()
        self.service.deposit(10_000)
        bought = self.service.buy("BTC", 0.1)
        sold = self.service.sell("BTC", 0.04)
        self.assertEqual(bought.usd_value, 5_000)
        self.assertEqual(sold.usd_value, 2_000)
        self.assertTrue(math.isclose(self._balances()["BTC"], 0.06))
        self.assertEqual(self._balances()["USD"], 7_000)
        transactions = self.database.read("portfolios.json")[0].get("transactions", [])
        self.assertEqual(
            [item["action"] for item in transactions], ["DEPOSIT", "BUY", "SELL"]
        )
        self.assertEqual(self.service.show_portfolio().total, 10_000)

    def test_failed_trades_do_not_change_persisted_balances(self) -> None:
        self._login()
        self.service.deposit(100)
        before = self.database.read("portfolios.json")
        with self.assertRaises(InsufficientFundsError):
            self.service.buy("BTC", 1)
        with self.assertRaises(WalletNotFoundError):
            self.service.sell("BTC", 0.01)
        with self.assertRaises(CurrencyNotFoundError):
            self.service.buy("ABC", 1)
        with self.assertRaises(ValidationError):
            self.service.buy("BTC", math.nan)
        self.assertEqual(self.database.read("portfolios.json"), before)

    def test_failed_portfolio_write_preserves_balances_and_history(self) -> None:
        self._login()
        self.service.deposit(10_000)
        before = self.database.read("portfolios.json")
        original_write = self.database.write

        def fail_trade_write(filename: str, data: object) -> None:
            if filename == "portfolios.json":
                raise StorageError("Имитация сбоя записи")
            original_write(filename, data)

        with patch.object(self.database, "write", side_effect=fail_trade_write):
            with self.assertRaises(StorageError):
                self.service.buy("BTC", 0.01)
        self.assertEqual(self.database.read("portfolios.json"), before)
        self.assertIsNone(self.database.read("transactions.json"))

    def test_sell_insufficient_funds_preserves_wallet(self) -> None:
        self._login()
        self.service.deposit(5_000)
        self.service.buy("BTC", 0.01)
        before = self.database.read("portfolios.json")
        with self.assertRaises(InsufficientFundsError):
            self.service.sell("BTC", 0.02)
        self.assertEqual(self.database.read("portfolios.json"), before)

    def test_portfolio_conversion_requires_fresh_rate(self) -> None:
        self._login()
        self.service.deposit(100)
        self.assertAlmostEqual(self.service.show_portfolio("EUR").total, 100 / 1.2)
        stale = iso_utc(utc_now() - timedelta(hours=1))
        self.database.write(
            "rates.json",
            {
                "pairs": {"EUR_USD": {"rate": 1.2, "updated_at": stale}},
                "last_refresh": stale,
            },
        )
        with self.assertRaises(RateUnavailableError):
            self.service.show_portfolio("EUR")


if __name__ == "__main__":
    unittest.main()
