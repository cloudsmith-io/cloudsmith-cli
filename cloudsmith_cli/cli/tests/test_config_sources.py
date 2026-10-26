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


def test_empty_keys_of_the_default_config_set_nothing(monkeypatch, tmp_path):
    # `cloudsmith auth` writes the packaged default config.ini, whose keys are
    # mostly empty (`api_host=`); they must not count as set in the file.
    from importlib import resources

    template = resources.files("cloudsmith_cli.data").joinpath("config.ini")
    (tmp_path / "config.ini").write_text(template.read_text())
    _point_readers(monkeypatch, tmp_path)
    found = config_sources.detect(config_file=None, creds_file=None, profile=None)
    assert found == {"ssl_verify_strict": "config_file"}


def test_keys_are_the_names_as_written_in_default_and_profile(monkeypatch, tmp_path):
    (tmp_path / "config.ini").write_text(
        "[default]\norg = acme\napi_host =\nmy_secret_token = x\n\n"
        "[profile:ci]\napi_proxy = http://proxy.example:3128\n"
        "[profile:other]\nworkspace = other\n"
    )
    (tmp_path / "credentials.ini").write_text("[profile:ci]\napi_key = not-real\n")
    _point_readers(monkeypatch, tmp_path)
    # The renamed key keeps its old name; empty and undeclared keys are left out.
    assert config_sources.keys(config_file=None, creds_file=None, profile="ci") == [
        "api_key",
        "api_proxy",
        "org",
    ]
    assert config_sources.keys(config_file=None, creds_file=None, profile=None) == [
        "org"
    ]
