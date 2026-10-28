"""Tests for the text encoding of config.ini and credentials.ini."""

from __future__ import annotations

import builtins
import configparser
import io
import locale
from pathlib import Path
from typing import IO

import pytest

from cloudsmith_cli.cli import config as cli_config

FILE_TEXTS = [
    pytest.param("utf-8", "путь с", id="utf-8"),
    pytest.param("utf-8-sig", "путь с", id="utf-8-with-bom"),
    pytest.param("cp1252", "José", id="cp1252"),
]


@pytest.fixture(name="cp1252_locale")
def fixture_cp1252_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use cp1252 as the locale encoding, as Windows does without UTF-8 mode."""

    def open_with_cp1252_default(
        file: str | Path,
        mode: str = "r",
        *args: object,
        encoding: str | None = None,
        **kwargs: object,
    ) -> IO:
        if "b" not in mode and encoding in (None, "locale"):
            encoding = "cp1252"
        return builtins.open(file, mode, *args, encoding=encoding, **kwargs)

    monkeypatch.setattr(io, "text_encoding", lambda encoding, *_: encoding or "locale")
    monkeypatch.setattr(configparser, "open", open_with_cp1252_default, raising=False)
    monkeypatch.setattr(cli_config, "open", open_with_cp1252_default, raising=False)
    monkeypatch.setattr(locale, "getpreferredencoding", lambda *_: "cp1252")


@pytest.mark.windows
@pytest.mark.usefixtures("cp1252_locale")
@pytest.mark.parametrize(("encoding", "text"), FILE_TEXTS)
def test_config_file_loads_and_keeps_its_encoding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, encoding: str, text: str
) -> None:
    path = tmp_path / "config.ini"
    path.write_bytes(f"[default]\n# {text}\nworkspace = old\n".encode(encoding))
    monkeypatch.setattr(cli_config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(cli_config.ConfigReader, "config_searchpath", [str(tmp_path)])
    opts = cli_config.Options()

    cli_config.ConfigReader.load_config(opts)
    cli_config.ConfigReader.save_workspace("new", path=str(path))

    assert opts.workspace == "old"
    assert path.read_bytes().replace(b"\r\n", b"\n") == (
        f"[default]\n# {text}\nworkspace = new\n".encode(encoding)
    )


@pytest.mark.windows
@pytest.mark.usefixtures("cp1252_locale")
@pytest.mark.parametrize(("encoding", "text"), FILE_TEXTS)
def test_credentials_file_keeps_its_encoding(
    tmp_path: Path, encoding: str, text: str
) -> None:
    path = tmp_path / "credentials.ini"
    path.write_bytes(f"[default]\n# {text}\napi_key = old\n".encode(encoding))

    cli_config.CredentialsReader.update_api_key(str(path), "new")

    assert path.read_bytes() == (
        f"[default]\n# {text}\napi_key = new\n".encode(encoding)
    )
