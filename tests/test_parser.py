import copy
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


class FakeDatabase:
    def __init__(self) -> None:
        self.files: dict[str, Any] = {}

    def read(self, filename: str, default: object) -> object:
        return copy.deepcopy(self.files.get(Path(filename).name, default))

    def write(self, filename: str, data: object) -> None:
        self.files[Path(filename).name] = copy.deepcopy(data)

    @contextmanager
    def transaction(self) -> Iterator["FakeDatabase"]:
        yield self


class FakeClient(BaseApiClient):
    def __init__(
        self,
        name: str,
        rates: dict[str, float] | None = None,
        error: ApiRequestError | None = None,
    ) -> None:
        self.name = name
        self.rates = rates or {}
        self.error = error

    def fetch_rates(self) -> dict[str, float]:
        if self.error is not None:
            raise self.error
        return self.rates


class ApiClientsTests(unittest.TestCase):
    @patch("valutatrade_hub.parser_service.api_clients.requests.get")
    def test_coingecko_normalizes_by_id(self, get: Mock) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "bitcoin": {"usd": 59337.21},
            "ethereum": {"usd": 3720.0},
        }
        get.return_value = response
        config = ParserConfig(
            coingecko_api_key="demo-key", crypto_currencies=("BTC", "ETH")
        )

        rates = CoinGeckoClient(config).fetch_rates()

        self.assertEqual(rates, {"BTC_USD": 59337.21, "ETH_USD": 3720.0})
        self.assertEqual(get.call_args.kwargs["params"]["ids"], "bitcoin,ethereum")
        self.assertEqual(get.call_args.kwargs["timeout"], config.request_timeout)
        self.assertEqual(
            get.call_args.kwargs["headers"], {"x-cg-demo-api-key": "demo-key"}
        )

    @patch("valutatrade_hub.parser_service.api_clients.requests.get")
    def test_exchangerate_inverts_usd_base(self, get: Mock) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "result": "success",
            "base_code": "USD",
            "conversion_rates": {"EUR": 0.8, "GBP": 0.5},
        }
        get.return_value = response
        config = ParserConfig(
            exchangerate_api_key="test-key", fiat_currencies=("EUR", "GBP")
        )

        rates = ExchangeRateApiClient(config).fetch_rates()

        self.assertEqual(rates, {"EUR_USD": 1.25, "GBP_USD": 2.0})
        self.assertIn("/test-key/latest/USD", get.call_args.args[0])

    @patch("valutatrade_hub.parser_service.api_clients.requests.get")
    def test_http_rate_limit_is_actionable(self, get: Mock) -> None:
        get.return_value = Mock(status_code=429)
        with self.assertRaisesRegex(ApiRequestError, "лимит запросов"):
            CoinGeckoClient().fetch_rates()

    @patch("valutatrade_hub.parser_service.api_clients.requests.get")
    def test_network_error_hides_key(self, get: Mock) -> None:
        get.side_effect = requests.exceptions.Timeout("secret-key in URL")
        config = ParserConfig(exchangerate_api_key="secret-key")
        with self.assertRaises(ApiRequestError) as caught:
            ExchangeRateApiClient(config).fetch_rates()
        self.assertNotIn("secret-key", str(caught.exception))

    @patch("valutatrade_hub.parser_service.api_clients.requests.get")
    def test_invalid_rate_is_rejected(self, get: Mock) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"bitcoin": {"usd": True}}
        get.return_value = response
        config = ParserConfig(crypto_currencies=("BTC",))
        with self.assertRaises(ApiRequestError):
            CoinGeckoClient(config).fetch_rates()


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FakeDatabase()
        self.storage = RatesStorage(cast(DatabaseManager, self.database))

    def test_newer_rate_wins_and_history_deduplicates(self) -> None:
        first = "2025-10-10T12:00:00Z"
        second = "2025-10-10T12:01:00Z"
        self.storage.save_rates(
            {"BTC_USD": {"rate": 10.0, "updated_at": first, "source": "coingecko"}},
            first,
        )
        unchanged = self.storage.save_rates(
            {"BTC_USD": {"rate": 9.0, "updated_at": first, "source": "coingecko"}},
            first,
        )
        updated = self.storage.save_rates(
            {"BTC_USD": {"rate": 11.0, "updated_at": second, "source": "coingecko"}},
            second,
        )

        self.assertEqual((unchanged, updated), (0, 1))
        self.assertEqual(self.storage.read_cache()["pairs"]["BTC_USD"]["rate"], 11.0)
        self.assertEqual(len(self.database.files["exchange_rates.json"]), 2)
        self.assertEqual(
            self.database.files["exchange_rates.json"][1]["id"], f"BTC_USD_{second}"
        )

    def test_older_rate_does_not_replace_newer_or_refresh_snapshot(self) -> None:
        newer = "2025-10-10T12:01:00Z"
        older = "2025-10-10T12:00:00Z"
        self.storage.save_rates(
            {"EUR_USD": {"rate": 1.2, "updated_at": newer, "source": "exchangerate"}},
            newer,
        )
        result = self.storage.save_rates(
            {"EUR_USD": {"rate": 1.1, "updated_at": older, "source": "exchangerate"}},
            older,
        )

        self.assertEqual(result, 0)
        self.assertEqual(self.storage.read_cache()["last_refresh"], newer)
        self.assertEqual(self.storage.read_cache()["pairs"]["EUR_USD"]["rate"], 1.2)


class UpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FakeDatabase()
        self.storage = RatesStorage(cast(DatabaseManager, self.database))

    def test_partial_failure_preserves_other_source(self) -> None:
        older = "2025-10-10T12:00:00Z"
        self.storage.save_rates(
            {"EUR_USD": {"rate": 1.1, "updated_at": older, "source": "exchangerate"}},
            older,
        )
        updater = RatesUpdater(
            clients=(
                FakeClient("coingecko", {"BTC_USD": 20.0}),
                FakeClient("exchangerate", error=ApiRequestError("quota")),
            ),
            storage=self.storage,
        )

        result = updater.run_update()

        self.assertEqual(result.updated_count, 1)
        self.assertIn("exchangerate", result.errors)
        self.assertEqual(self.storage.read_cache()["pairs"]["EUR_USD"]["rate"], 1.1)
        self.assertEqual(self.storage.read_cache()["pairs"]["BTC_USD"]["rate"], 20.0)

    def test_all_fail_does_not_touch_files(self) -> None:
        updater = RatesUpdater(
            clients=(FakeClient("coingecko", error=ApiRequestError("network")),),
            storage=self.storage,
        )
        with self.assertRaises(ApiRequestError):
            updater.run_update()
        self.assertEqual(self.database.files, {})


if __name__ == "__main__":
    unittest.main()
