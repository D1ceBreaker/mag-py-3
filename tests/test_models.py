import math
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    FiatCurrency,
    get_currency,
    supported_codes,
)
from valutatrade_hub.core.exceptions import (
    CurrencyNotFoundError,
    InsufficientFundsError,
    ValidationError,
    WalletNotFoundError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import cached_rates, iso_utc, parse_timestamp


class UserTests(unittest.TestCase):
    def test_password_is_salted_and_serialization_excludes_plaintext(self) -> None:
        first = User.create(1, " alice ", "pass1234")
        second = User.create(2, "bob", "pass1234")
        self.assertEqual(first.username, "alice")
        self.assertNotEqual(first.salt, second.salt)
        self.assertNotEqual(first.hashed_password, second.hashed_password)
        self.assertTrue(first.verify_password("pass1234"))
        self.assertFalse(first.verify_password("wrong"))
        data = first.to_dict()
        self.assertNotIn("pass1234", str(data))
        self.assertNotIn("hashed_password", first.get_user_info())
        restored = User.from_dict(data)
        self.assertTrue(restored.verify_password("pass1234"))
        self.assertEqual(restored.registration_date.tzinfo, UTC)

    def test_password_change_rotates_salt(self) -> None:
        user = User.create(1, "alice", "initial")
        old_salt = user.salt
        user.change_password("updated")
        self.assertNotEqual(user.salt, old_salt)
        self.assertFalse(user.verify_password("initial"))
        self.assertTrue(user.verify_password("updated"))

    def test_invalid_user_values(self) -> None:
        with self.assertRaises(ValidationError):
            User.create(1, " ", "valid")
        with self.assertRaises(ValidationError):
            User.create(1, "alice", "123")
        with self.assertRaises(ValidationError):
            User.create(0, "alice", "valid")


class WalletTests(unittest.TestCase):
    def test_balance_invariants_and_insufficient_funds(self) -> None:
        wallet = Wallet("usd")
        wallet.deposit(100.0)
        wallet.withdraw(25.0)
        self.assertEqual(wallet.balance, 75.0)
        with self.assertRaises(InsufficientFundsError):
            wallet.withdraw(75.01)
        self.assertEqual(wallet.balance, 75.0)
        for invalid in (-1, math.nan, math.inf, True, "10"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                wallet.balance = invalid
        for invalid in (0, -1, math.nan, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                wallet.deposit(invalid)


class PortfolioTests(unittest.TestCase):
    def test_roundtrip_and_conversion(self) -> None:
        user = User.create(1, "alice", "valid")
        portfolio = Portfolio(
            user,
            rate_provider=lambda source, target: {
                ("BTC", "USD"): 50_000.0,
                ("USD", "EUR"): 0.9,
                ("BTC", "EUR"): 45_000.0,
            }[(source, target)],
        )
        portfolio.add_currency("USD").deposit(100.0)
        portfolio.add_currency("BTC").deposit(0.01)
        self.assertIs(portfolio.add_currency("btc"), portfolio.get_wallet("BTC"))
        self.assertEqual(portfolio.get_total_value(), 600.0)
        self.assertEqual(portfolio.get_total_value("EUR"), 540.0)
        wallets = portfolio.wallets
        wallets.clear()
        self.assertEqual(len(portfolio.wallets), 2)
        restored = Portfolio.from_dict(portfolio.to_dict(), user)
        self.assertEqual(restored.get_wallet("BTC").balance, 0.01)

    def test_missing_wallet_and_invalid_base(self) -> None:
        portfolio = Portfolio(User.create(1, "alice", "valid"))
        with self.assertRaises(WalletNotFoundError):
            portfolio.get_wallet("EUR")
        with self.assertRaises(CurrencyNotFoundError):
            portfolio.get_total_value("ABC")


class CurrencyTests(unittest.TestCase):
    def test_registry_and_display(self) -> None:
        self.assertIsInstance(get_currency(" usd "), FiatCurrency)
        self.assertIsInstance(get_currency("btc"), CryptoCurrency)
        self.assertIn("Issuing: United States", get_currency("USD").get_display_info())
        self.assertIn("Algo: SHA-256", get_currency("BTC").get_display_info())
        self.assertIn("SOL", supported_codes())
        with self.assertRaises(CurrencyNotFoundError):
            get_currency("ABC")


class UtilsTests(unittest.TestCase):
    def test_timestamp_roundtrip(self) -> None:
        moment = datetime(2025, 10, 9, 12, 0, tzinfo=UTC)
        self.assertEqual(parse_timestamp(iso_utc(moment)), moment)
        self.assertEqual(parse_timestamp("2025-10-09T12:00:00"), moment)

    def test_ttl_closure_reuses_then_expires(self) -> None:
        call_count = 0

        @cached_rates(5)
        def value(code: str) -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        with patch("valutatrade_hub.core.utils.time.monotonic", side_effect=[1, 4, 7]):
            self.assertEqual(value("USD"), 1)
            self.assertEqual(value("USD"), 1)
            self.assertEqual(value("USD"), 2)
        self.assertEqual(call_count, 2)

    def test_ttl_closure_caps_distinct_keys(self) -> None:
        call_count = 0

        @cached_rates(5)
        def value(code: int) -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        with patch("valutatrade_hub.core.utils.time.monotonic", return_value=1):
            for code in range(129):
                value(code)
            self.assertEqual(value(0), 130)
            self.assertEqual(value(128), 129)

    def test_ttl_closure_purges_expired_entries(self) -> None:
        call_count = 0

        @cached_rates(5)
        def value(code: int) -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        with patch(
            "valutatrade_hub.core.utils.time.monotonic", side_effect=[1, 2, 7, 7]
        ):
            self.assertEqual(value(1), 1)
            self.assertEqual(value(2), 2)
            self.assertEqual(value(1), 3)
            self.assertEqual(value(2), 4)


if __name__ == "__main__":
    unittest.main()
