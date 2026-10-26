from cloudsmith_cli.cli import config, config_sources


def _point_readers(monkeypatch, path):
    for reader in (config.ConfigReader, config.CredentialsReader):
        monkeypatch.setattr(reader, "config_searchpath", [str(path)])
    monkeypatch.setattr(config.ConfigReader, "config_files", ["config.ini"])
    monkeypatch.setattr(config.CredentialsReader, "config_files", ["credentials.ini"])


def test_detects_default_and_profile_keys_not_defaults(monkeypatch, tmp_path):
    (tmp_path / "config.ini").write_text(
        "[default]\nworkspace = acme\n\n[profile:ci]\ncheck_for_update = false\n"
    )
    (tmp_path / "credentials.ini").write_text("[profile:ci]\napi_key = not-real\n")
    _point_readers(monkeypatch, tmp_path)
    found = config_sources.detect(config_file=None, creds_file=None, profile="ci")
    assert found == {
        "workspace": "config_file",
        "check_for_update": "config_profile",
        "api_key": "credentials_profile",
    }
    assert "telemetry" not in found and "ssl_verify" not in found


def test_reports_only_schema_declared_keys_for_each_file(monkeypatch, tmp_path):
    (tmp_path / "config.ini").write_text(
        "[default]\nworkspace = acme\nmy_secret_token = x\n"
    )
    (tmp_path / "credentials.ini").write_text(
        "[default]\napi_key = not-real\nworkspace = other\n"
    )
    _point_readers(monkeypatch, tmp_path)
    found = config_sources.detect(config_file=None, creds_file=None, profile=None)
    assert found == {"workspace": "config_file", "api_key": "credentials_file"}


def test_unreadable_file_is_ignored(monkeypatch, tmp_path):
    (tmp_path / "config.ini").write_text("[default\nbroken")
    _point_readers(monkeypatch, tmp_path)
    assert not config_sources.detect(config_file=None, creds_file=None, profile=None)
