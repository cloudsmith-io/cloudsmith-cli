# Copyright 2026 Cloudsmith Ltd
from pathlib import Path

from typing_extensions import Self


class AuthKeyConflictError(KeyError):
    """Raised when adding tokenHelper but auth is already set"""


class NPMRC:
    class URLEntry(str):
        _key: str
        _value: str | None

        @classmethod
        def from_values(cls, domain: str, key: str, value: str | None = None):
            obj = cls(
                f"//{domain}/:{key}=" if value is None else f"//{domain}/:{key}={value}"
            )
            if value is None:
                obj._value = None
            return obj

        @property
        def id(self) -> str:
            return f"{self._domain}::{self._key}"

        def __new__(cls, value):
            obj = super().__new__(cls, value)
            return obj

        def __init__(self, entry: str):
            self._raw: str = entry

            ## if line contains trailing comment, ignore
            for i, c in enumerate(entry):
                if c in ";#":
                    entry = entry[:i]
                    break

            # remove any starting whitespace
            stripped_entry = entry.lstrip()

            # track the starting whitespace
            self._leading = entry[: len(entry) - len(stripped_entry)]
            if not stripped_entry.startswith("/"):
                raise ValueError("invalid url, should start with ``//``")

            stripped_entry = stripped_entry.lstrip("/")

            domain, kv = stripped_entry.split(":", 1)
            self._domain = domain.rstrip("/")
            if not self._domain:
                raise ValueError(f"entry {self._raw} is missing domain")

            self._key, self._value = kv.split("=", 1)
            if not self._key:
                raise ValueError(f"entry {self._raw} is missing key")

        def __str__(self) -> str:
            return f"{self._leading}//{self._domain}/:{self._key}={self._value}"

    @property
    def modified(self):
        return self._modified

    @property
    def failures(self):
        return self._failures

    def __init__(self, path: Path, modifiable=False) -> None:
        self._failures = 0
        self._modifiable = modifiable
        self._modified = False
        self._path: Path = path
        self._lines: list[str | NPMRC.URLEntry] = []
        self._mapping: dict[str, str | None] = {}

    def __enter__(self) -> Self:
        if not self._path.exists():
            if self._modifiable:
                self._path.touch()
            else:
                return self

        self.parse()

        return self

    def __exit__(self, *_):
        self.write()
        return False

    def __contains__(self, item: str | URLEntry) -> bool:
        if isinstance(item, NPMRC.URLEntry):
            return item.id in self._mapping and (
                item._value is None or self._mapping[item.id] == item._value
            )

        return any(item in line for line in self._lines)

    def create_if_not_exists(self):
        if not self._path.exists():
            self._path.touch()

    def parse(self):
        with open(self._path) as f:
            for line in f:
                if line.lstrip().startswith("//"):
                    try:
                        entry = NPMRC.URLEntry(line.rstrip("\n"))
                        self._lines.append(entry)
                        self._mapping[entry.id] = entry._value
                    except Exception:
                        self._lines.append(line.rstrip("\n"))
                else:
                    self._lines.append(line.rstrip("\n"))

    def add(self, entry: URLEntry) -> bool:
        if entry in self:
            return False

        if NPMRC.URLEntry.from_values(entry._domain, entry._key) in self:
            for i, line in enumerate(self._lines):
                if isinstance(line, NPMRC.URLEntry) and line.id == entry.id:
                    self._lines[i] = entry
                    break

            self._modified = True
            self._mapping[entry.id] = entry._value
            return True

        if NPMRC.URLEntry.from_values(entry._domain, "_authToken") in self:
            self._failures += 1
            raise AuthKeyConflictError("_authToken")

        if NPMRC.URLEntry.from_values(entry._domain, "_auth") in self:
            self._failures += 1
            raise AuthKeyConflictError("_auth")

        if NPMRC.URLEntry.from_values(entry._domain, "_password") in self:
            self._failures += 1
            raise AuthKeyConflictError("_password")

        self._mapping[entry.id] = entry._value
        self._lines.append(entry)
        self._modified = True
        return True

    def remove(self, entry: URLEntry) -> bool:
        if entry.id not in self._mapping:
            return False

        for i, line in enumerate(self._lines):
            if (
                isinstance(line, NPMRC.URLEntry)
                and line._domain == entry._domain
                and line._key == entry._key
            ):
                self._lines.pop(i)
                del self._mapping[line.id]
                self._modified = True
                return True

        return False

    def helped_hosts(self, v: str) -> list[str]:
        return [
            line._domain
            for line in self._lines
            if isinstance(line, NPMRC.URLEntry)
            and line._key == "tokenHelper"
            and line._value == v
        ]

    def write(self):
        if not self._modifiable:
            return

        if not self.modified:
            return

        with open(self._path, "w") as f:
            f.write("\n".join(self._lines))
