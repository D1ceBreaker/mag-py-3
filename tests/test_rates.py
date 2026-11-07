import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from valutatrade_hub.core.exceptions import (
    CurrencyNotFoundError,
    RateUnavailableError,
    StorageError,
    ValidationError,
)
from valutatrade_hub.core.rates import RatesService
from valutatrade_hub.core.utils import iso_utc, utc_now
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class RatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ, {"VALUTATRADE_DATA_DIR": self.directory.name}
        )
        self.environment.start()
        SettingsLoader().reload()
        self.database = DatabaseManager()

    def tearDown(self) -> None:
        self.environment.stop()
        SettingsLoader().reload()
        self.directory.cleanup()

    def _write_rates(self, timestamp: str) -> None:
        self.database.write(
            "rates.json",
            {
                "pairs": {
                    "BTC_USD": {
                        "rate": 60_000.0,
                        "updated_at": timestamp,
                        "source": "CoinGecko",
                    },
                    "ETH_USD": {
                        "rate": 3_000.0,
                        "updated_at": timestamp,
                        "source": "CoinGecko",
                    },
                    "EUR_USD": {
                        "rate": 1.2,
                        "updated_at": timestamp,
                        "source": "ExchangeRate-API",
                    },
                },
                "last_refresh": timestamp,
            },
        )

    def test_direct_inverse_cross_and_identity(self) -> None:
        self._write_rates(iso_utc())
        refresh = Mock()
        rates = RatesService(self.database, refresh=refresh)
        self.assertEqual(rates.get_rate("BTC", "USD").rate, 60_000)
        self.assertAlmostEqual(rates.get_rate("USD", "EUR").rate, 1 / 1.2)
        self.assertAlmostEqual(rates.get_rate("EUR", "BTC").rate, 1.2 / 60_000)
        self.assertEqual(rates.get_rate("USD", "USD").rate, 1)
        refresh.assert_not_called()

    def test_unknown_currency_rejected_before_refresh(self) -> None:
        refresh = Mock()
        rates = RatesService(self.database, refresh=refresh)
        with self.assertRaises(CurrencyNotFoundError):
            rates.get_rate("ABC", "USD")
        refresh.assert_not_called()

    def test_stale_leg_cannot_satisfy_cross_rate(self) -> None:
        fresh = iso_utc()
        stale = iso_utc(utc_now() - timedelta(hours=1))
        self.database.write(
            "rates.json",
            {
                "pairs": {
                    "BTC_USD": {"rate": 60_000.0, "updated_at": fresh},
                    "EUR_USD": {"rate": 1.2, "updated_at": stale},
                },
                "last_refresh": fresh,
            },
        )
        refresh = Mock()
        rates = RatesService(self.database, refresh=refresh)
        with self.assertRaises(RateUnavailableError):
            rates.get_rate("EUR", "BTC")
        refresh.assert_called_once()

    def test_refresh_reloads_file_immediately(self) -> None:
        self._write_rates(iso_utc(utc_now() - timedelta(hours=1)))
        updated = iso_utc()

        def refresh() -> None:
            self.database.write(
                "rates.json",
                {
                    "pairs": {"BTC_USD": {"rate": 42_000.0, "updated_at": updated}},
                    "last_refresh": updated,
                },
            )

        rates = RatesService(self.database, refresh=refresh)
        self.assertEqual(rates.get_rate("BTC", "USD").rate, 42_000)
        self.assertEqual(rates.get_rate("BTC", "USD").rate, 42_000)

    def test_top_only_crypto_and_stale_marker(self) -> None:
        stale = iso_utc(utc_now() - timedelta(hours=1))
        self._write_rates(stale)
        refresh = Mock()
        rates = RatesService(self.database, refresh=refresh)
        rows = rates.list_rates(top=2)
        self.assertEqual([row.currency_code for row in rows], ["BTC", "ETH"])
        self.assertTrue(all(row.stale for row in rows))
        self.assertEqual(rates.list_rates(currency_code="EUR")[0].quote.rate, 1.2)
        refresh.assert_not_called()

    def test_empty_cache_and_invalid_top(self) -> None:
        rates = RatesService(self.database, refresh=Mock())
        with self.assertRaises(ValidationError):
            rates.list_rates()
        for invalid in (0, -1, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                rates.list_rates(top=invalid)

    def test_invalid_rate_cannot_be_used(self) -> None:
        timestamp = iso_utc()
        self.database.write(
            "rates.json",
            {
                "pairs": {"BTC_USD": {"rate": -1, "updated_at": timestamp}},
                "last_refresh": timestamp,
            },
        )
        rates = RatesService(self.database, refresh=Mock())
        with self.assertRaises(StorageError):
            rates.get_rate("BTC", "USD")


if __name__ == "__main__":
    unittest.main()
