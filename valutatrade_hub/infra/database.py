import fcntl
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock
from typing import Any, ClassVar, Self, TextIO

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Единственный менеджер JSON-хранилища в процессе.

    Реализация через ``__new__`` сохраняет общую потоковую блокировку
    без отдельного метакласса.
    """

    _instance: ClassVar[Self | None] = None
    _creation_lock: ClassVar[Lock] = Lock()
    _mutex: RLock
    _depth: int

    def __new__(cls) -> Self:
        """Возвращает экземпляр с повторно используемой блокировкой."""
        with cls._creation_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._mutex = RLock()
                instance._depth = 0
                cls._instance = instance
            return cls._instance

    @contextmanager
    def transaction(self) -> Generator[Self, None, None]:
        """Блокирует операции на время работы внутри контекста.

        Повторный вход использует ту же блокировку. Потоки синхронизируются
        через RLock, процессы — через файловую блокировку. Общего отката
        изменений нескольких JSON-файлов этот контекст не выполняет.
        """
        with self._mutex:
            lock_file: TextIO | None = None
            try:
                directory = SettingsLoader().data_dir
                directory.mkdir(parents=True, exist_ok=True)
                if self._depth == 0:
                    lock_file = (directory / ".lock").open("a", encoding="utf-8")
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                self._depth += 1
            except OSError as error:
                if lock_file is not None:
                    lock_file.close()
                raise StorageError("Не удалось открыть хранилище данных") from error
            try:
                yield self
            finally:
                self._depth -= 1
                if lock_file is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()

    def read(self, filename: str, default: Any = None) -> Any:
        """Читает JSON или возвращает default, если файл отсутствует."""
        with self.transaction():
            path = SettingsLoader().path(filename)
            try:
                with path.open(encoding="utf-8") as file:
                    return json.load(file)
            except FileNotFoundError:
                return default
            except (OSError, ValueError) as error:
                raise StorageError(
                    f"Не удалось прочитать файл '{path.name}'"
                ) from error

    def write(self, filename: str, data: Any) -> None:
        """Сохраняет один JSON-файл через временный файл и замену."""
        with self.transaction():
            path = SettingsLoader().path(filename)
            temporary: Path | None = None
            try:
                payload = json.dumps(
                    data, ensure_ascii=False, indent=2, allow_nan=False
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    suffix=".tmp",
                    delete=False,
                ) as file:
                    temporary = Path(file.name)
                    file.write(payload + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
            except (OSError, ValueError, TypeError) as error:
                raise StorageError(
                    f"Не удалось сохранить файл '{path.name}'"
                ) from error
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
