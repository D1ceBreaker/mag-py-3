import os
import tomllib
from pathlib import Path
from threading import Lock
from typing import Any, ClassVar, Self

from valutatrade_hub.core.exceptions import ValidationError


class SettingsLoader:
    """Единственный загрузчик настроек в процессе.

    Реализация через ``__new__`` позволяет повторно использовать экземпляр
    без отдельного метакласса.
    """

    _instance: ClassVar[Self | None] = None
    _lock: ClassVar[Lock] = Lock()
    _values: dict[str, Any]

    def __new__(cls) -> Self:
        """Возвращает общий экземпляр и при создании загружает настройки."""
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.reload()
                cls._instance = instance
            return cls._instance

    def reload(self) -> None:
        """Перечитывает настройки и проверяет допустимость числовых значений."""
        values: dict[str, Any] = {
            "data_dir": "data",
            "rates_ttl_seconds": 300,
            "default_base_currency": "USD",
            "log_dir": "logs",
            "log_format": "json",
            "log_max_bytes": 1048576,
            "log_backup_count": 3,
        }
        config_path = Path(os.getenv("VALUTATRADE_CONFIG", "pyproject.toml"))
        try:
            if config_path.exists():
                with config_path.open("rb") as file:
                    values.update(
                        tomllib.load(file).get("tool", {}).get("valutatrade", {})
                    )
            for key in values:
                override = os.getenv(f"VALUTATRADE_{key.upper()}")
                if override is not None:
                    values[key] = override
            for key in ("rates_ttl_seconds", "log_max_bytes", "log_backup_count"):
                values[key] = int(values[key])
                if values[key] <= 0:
                    raise ValueError(key)
            if values["log_format"] not in {"json", "text"}:
                raise ValueError("log_format")
        except (OSError, ValueError, TypeError) as error:
            raise ValidationError(
                "Не удалось загрузить настройки приложения"
            ) from error
        self._values = values

    def get(self, key: str, default: Any = None) -> Any:
        """Возвращает значение настройки или указанное значение по умолчанию."""
        return self._values.get(key, default)

    @property
    def data_dir(self) -> Path:
        """Возвращает абсолютный путь к каталогу данных."""
        return Path(str(self.get("data_dir"))).expanduser().resolve()

    @property
    def rates_ttl_seconds(self) -> int:
        """Возвращает допустимый возраст курса в секундах."""
        return int(self.get("rates_ttl_seconds"))

    def path(self, filename: str) -> Path:
        """Возвращает путь в каталоге данных или переданный абсолютный путь."""
        return self.data_dir / filename
