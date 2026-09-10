# Copyright 2026 Cloudsmith Ltd
"""Tests for cloudsmith_cli.core.update_check.

These cover the decision about when to fetch, the manifest fetch/parse, the
once-a-day "update available" notice and its suppression, and state
persistence. The network is stubbed throughout via a fake requests session.
"""

from __future__ import annotations

import json
import os

import pytest
import requests
import semver

from cloudsmith_cli.core import update_check

# A fixed "current" version so tests do not break when VERSION is bumped.
CURRENT_VERSION = "1.26.0"
NEWER_VERSION = "2.0.0"
OLDER_VERSION = "1.0.0"

DAY = update_check.DEFAULT_INTERVAL_SECONDS
NOW = 1_000_000.0


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    """Point the state file at a temp location and pin the current version."""
    path = str(tmp_path / "update_check.json")
    monkeypatch.setattr(update_check, "get_state_file_path", lambda: path)
    monkeypatch.setattr(
        update_check.version,
        "get_version_info",
        lambda: semver.VersionInfo.parse(CURRENT_VERSION),
    )
    return path


def _write_state(path, last_check_at, latest_version=CURRENT_VERSION):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_check_at": last_check_at, "latest_version": latest_version}, f)


def _read_state(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class _FakeSession:
    """A stand-in requests session.

    Records whether ``get`` was called and returns a manifest body, or raises a
    ``requests.RequestException``, standing in for a successful or failed fetch.
    """

    def __init__(self, *, version_str=CURRENT_VERSION, fails=False):
        self.version = version_str
        self.fails = fails
        self.called = False

    def get(self, url, timeout=None):
        self.called = True
        if self.fails:
            raise requests.ConnectionError("network down")
        return _FakeResponse(f"schema=1\nversion={self.version}\n")


class _FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"status {self.status}")


def _run(session, *, now=NOW, no_check_flag=False, config_value=True, env=None):
    """Drive the real decision + fetch/notify path with a fake session.

    Mirrors ``arm`` minus the Click context: if a fetch is due, run the real
    ``run_background_check`` synchronously; if we already know we are behind,
    notify without fetching. Returns the session so tests can assert on it.
    """
    env = {} if env is None else env
    if not update_check.should_check_for_update(
        no_check_flag=no_check_flag, config_value=config_value, env=env, now=now
    ):
        return session
    if update_check.should_notify():
        update_check.record_check(update_check.read_latest_version(), now=now)
        return session
    update_check.run_background_check(session, now=now)
    return session


# ---------------------------------------------------------------------------
# The six required scenarios
# ---------------------------------------------------------------------------


class TestUpdateCheckDecision:
    def test_no_state_file_triggers_check_and_creates_file(self, state_path):
        """1. No state file → check runs and the file is created."""
        assert not os.path.exists(state_path)
        session = _run(_FakeSession(version_str=CURRENT_VERSION))
        assert session.called is True
        assert os.path.exists(state_path)
        assert _read_state(state_path)["last_check_at"] == NOW

    def test_stale_state_triggers_check_and_updates_file(self, state_path):
        """2. Stale timestamp → check runs and the file is updated."""
        _write_state(state_path, last_check_at=NOW - (DAY * 3))
        session = _run(_FakeSession(version_str=CURRENT_VERSION))
        assert session.called is True
        assert _read_state(state_path)["last_check_at"] == NOW

    def test_recent_state_skips_check_and_leaves_file(self, state_path):
        """3. Recent timestamp → check does not run and the file is untouched."""
        recent = NOW - 60.0
        _write_state(state_path, last_check_at=recent)
        before = os.stat(state_path).st_mtime_ns
        session = _run(_FakeSession(version_str=CURRENT_VERSION))
        assert session.called is False
        assert _read_state(state_path)["last_check_at"] == recent
        assert os.stat(state_path).st_mtime_ns == before

    def test_stale_but_newer_known_notifies_without_fetch(self, state_path):
        """4. Stale timestamp with a cached newer version → notify, no fetch.

        The timestamp is bumped (throttling the next notice), but no network
        fetch happens because we already know we are behind.
        """
        _write_state(
            state_path, last_check_at=NOW - (DAY * 3), latest_version=NEWER_VERSION
        )
        session = _run(_FakeSession(version_str=NEWER_VERSION))
        assert session.called is False
        after = _read_state(state_path)
        assert after["last_check_at"] == NOW
        assert after["latest_version"] == NEWER_VERSION

    def test_no_state_file_failed_check_does_not_create_file(self, state_path):
        """5. No state file and the check fails → the file is not created."""
        assert not os.path.exists(state_path)
        session = _run(_FakeSession(fails=True))
        assert session.called is True
        assert not os.path.exists(state_path)

    def test_stale_state_failed_check_does_not_update_file(self, state_path):
        """6. Stale state and the check fails → the file is not updated."""
        stale = NOW - (DAY * 3)
        _write_state(state_path, last_check_at=stale)
        session = _run(_FakeSession(fails=True))
        assert session.called is True
        assert _read_state(state_path)["last_check_at"] == stale


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


class TestNoticeThrottle:
    """The once-a-day throttle via the shared last_check_at timestamp."""

    def test_behind_and_recent_stays_silent(self, state_path):
        """Behind but checked recently → not due, file untouched, no fetch."""
        recent = NOW - 60.0
        _write_state(state_path, last_check_at=recent, latest_version=NEWER_VERSION)
        before = os.stat(state_path).st_mtime_ns
        session = _run(_FakeSession(version_str=NEWER_VERSION))
        assert session.called is False
        assert os.stat(state_path).st_mtime_ns == before

    def test_behind_and_stale_bumps_then_throttles(self, state_path):
        """Behind and stale → bump timestamp; an immediate re-run is throttled."""
        _write_state(
            state_path, last_check_at=NOW - (DAY * 2), latest_version=NEWER_VERSION
        )
        _run(_FakeSession(version_str=NEWER_VERSION), now=NOW)
        assert _read_state(state_path)["last_check_at"] == NOW

        # Same day, a minute later: not due, state untouched.
        before = os.stat(state_path).st_mtime_ns
        _run(_FakeSession(version_str=NEWER_VERSION), now=NOW + 60.0)
        assert os.stat(state_path).st_mtime_ns == before

        # A day later: due again, keeps the cached newer version.
        _run(_FakeSession(version_str=NEWER_VERSION), now=NOW + DAY + 60.0)
        assert _read_state(state_path)["last_check_at"] == NOW + DAY + 60.0
        assert _read_state(state_path)["latest_version"] == NEWER_VERSION

    def test_disable_control_suppresses_everything(self, state_path):
        """A disable control silences the fetch (and hence the notice)."""
        _write_state(
            state_path, last_check_at=NOW - (DAY * 2), latest_version=NEWER_VERSION
        )
        before = os.stat(state_path).st_mtime_ns
        session = _run(_FakeSession(version_str=NEWER_VERSION), config_value=False)
        assert session.called is False
        assert os.stat(state_path).st_mtime_ns == before


class TestShouldNotify:
    def test_true_when_cached_version_newer(self, state_path):
        _write_state(state_path, last_check_at=NOW, latest_version=NEWER_VERSION)
        assert update_check.should_notify() is True

    def test_false_when_up_to_date(self, state_path):
        _write_state(state_path, last_check_at=NOW, latest_version=CURRENT_VERSION)
        assert update_check.should_notify() is False

    def test_false_when_no_state(self, state_path):
        assert update_check.should_notify() is False

    def test_accepts_explicit_state(self, state_path):
        assert update_check.should_notify({"latest_version": NEWER_VERSION}) is True
        assert update_check.should_notify({"latest_version": OLDER_VERSION}) is False

    def test_current_version_override(self, state_path):
        state = {"latest_version": "1.5.0"}
        assert update_check.should_notify(state, current_version="1.0.0") is True
        assert update_check.should_notify(state, current_version="2.0.0") is False


class TestShouldCheckForUpdate:
    """should_check_for_update gates purely on disabled + freshness now."""

    def test_due_when_stale_even_if_behind(self, state_path):
        _write_state(
            state_path, last_check_at=NOW - (DAY * 2), latest_version=NEWER_VERSION
        )
        assert (
            update_check.should_check_for_update(
                no_check_flag=False, config_value=True, env={}, now=NOW
            )
            is True
        )

    def test_not_due_when_recent(self, state_path):
        _write_state(state_path, last_check_at=NOW - 60.0)
        assert (
            update_check.should_check_for_update(
                no_check_flag=False, config_value=True, env={}, now=NOW
            )
            is False
        )

    def test_due_when_no_state(self, state_path):
        assert (
            update_check.should_check_for_update(
                no_check_flag=False, config_value=True, env={}, now=NOW
            )
            is True
        )


class TestDisableControls:
    """The --no-check-update flag, env vars and config key suppress the check."""

    def test_no_check_flag_suppresses(self, state_path):
        session = _run(_FakeSession(), no_check_flag=True)
        assert session.called is False
        assert not os.path.exists(state_path)

    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_env_var_truthy_suppresses(self, state_path, value):
        session = _run(_FakeSession(), env={update_check.NO_UPDATE_CHECK_ENV: value})
        assert session.called is False

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_env_var_falsey_does_not_suppress(self, state_path, value):
        session = _run(_FakeSession(), env={update_check.NO_UPDATE_CHECK_ENV: value})
        assert session.called is True

    def test_ci_env_suppresses(self, state_path):
        session = _run(_FakeSession(), env={"CI": "true"})
        assert session.called is False

    def test_config_false_suppresses(self, state_path):
        session = _run(_FakeSession(), config_value=False)
        assert session.called is False

    def test_flag_wins_over_enabled_config(self, state_path):
        session = _run(_FakeSession(), no_check_flag=True, config_value=True)
        assert session.called is False


class TestIsCheckDue:
    def test_none_is_due(self):
        assert update_check.is_check_due(None, now=NOW) is True

    def test_invalid_is_due(self):
        assert update_check.is_check_due("not-a-number", now=NOW) is True

    def test_fresh_is_not_due(self):
        assert update_check.is_check_due(NOW - 60.0, now=NOW) is False

    def test_stale_is_due(self):
        assert update_check.is_check_due(NOW - DAY - 1, now=NOW) is True

    def test_exact_boundary_is_due(self):
        assert update_check.is_check_due(NOW - DAY, now=NOW) is True


class TestNewerVersionKnown:
    def test_newer_cached_version_is_known(self):
        assert update_check.newer_version_known(NEWER_VERSION, CURRENT_VERSION) is True

    def test_older_cached_version_is_not_newer(self):
        assert update_check.newer_version_known(OLDER_VERSION, CURRENT_VERSION) is False

    def test_equal_cached_version_is_not_newer(self):
        assert (
            update_check.newer_version_known(CURRENT_VERSION, CURRENT_VERSION) is False
        )

    def test_missing_cached_version_is_not_newer(self):
        assert update_check.newer_version_known(None, CURRENT_VERSION) is False

    def test_unparsable_cached_version_is_not_newer(self):
        assert update_check.newer_version_known("garbage", CURRENT_VERSION) is False


class TestStatePersistence:
    def test_record_and_read_round_trip(self, state_path):
        update_check.record_check(NEWER_VERSION, now=NOW)
        assert update_check.read_last_check_time() == NOW
        assert update_check.read_latest_version() == NEWER_VERSION

    def test_read_missing_file_returns_none(self, state_path):
        assert update_check.read_last_check_time() is None
        assert update_check.read_latest_version() is None
        assert update_check.read_cached_state() == {}

    def test_read_corrupt_file_returns_empty(self, state_path):
        with open(state_path, "w", encoding="utf-8") as f:
            f.write("not json")
        assert update_check.read_cached_state() == {}
        assert update_check.read_last_check_time() is None
        assert update_check.read_latest_version() is None

    def test_read_non_object_returns_empty(self, state_path):
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        assert update_check.read_cached_state() == {}

    def test_record_creates_parent_directory(self, tmp_path, monkeypatch):
        path = str(tmp_path / "nested" / "dir" / "update_check.json")
        monkeypatch.setattr(update_check, "get_state_file_path", lambda: path)
        update_check.record_check(CURRENT_VERSION, now=NOW)
        assert os.path.exists(path)

    def test_record_swallows_storage_errors(self, tmp_path, monkeypatch):
        # Point the state file at a path whose parent is a file, so makedirs fails.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        path = str(blocker / "update_check.json")
        monkeypatch.setattr(update_check, "get_state_file_path", lambda: path)
        # Must not raise.
        update_check.record_check(CURRENT_VERSION, now=NOW)
        assert not os.path.exists(path)


class TestParseManifest:
    def test_parses_key_value_lines(self):
        text = "version=1.27.0\ntarget=linux-x86_64-gnu\n"
        manifest = update_check.parse_manifest(text)
        assert manifest["version"] == "1.27.0"
        assert manifest["target"] == "linux-x86_64-gnu"

    def test_skips_comments_and_blanks(self):
        text = "# a comment\n\n  \nversion=1.27.0\n"
        assert update_check.parse_manifest(text) == {"version": "1.27.0"}

    def test_ignores_schema_but_keeps_it(self):
        text = "schema=1\nversion=1.27.0\n"
        manifest = update_check.parse_manifest(text)
        assert manifest["schema"] == "1"
        assert manifest["version"] == "1.27.0"

    def test_strips_whitespace(self):
        assert update_check.parse_manifest("  version = 1.27.0  ") == {
            "version": "1.27.0"
        }

    def test_lines_without_equals_are_skipped(self):
        assert update_check.parse_manifest("garbage\nversion=1.27.0") == {
            "version": "1.27.0"
        }


class TestFetchLatestManifest:
    @pytest.fixture(autouse=True)
    def _patch_httpretty_socket(self, monkeypatch):
        import httpretty.core

        monkeypatch.setattr(
            httpretty.core.fakesock.socket,
            "shutdown",
            lambda self, how: None,
            raising=False,
        )

    def _url(self, target=update_check.VERSION_PROBE_TARGET):
        return update_check.MANIFEST_URL_TEMPLATE.format(target=target)

    def test_fetches_and_parses(self):
        import httpretty

        from cloudsmith_cli.core.session import create_requests_session

        with httpretty.enabled(allow_net_connect=False):
            httpretty.register_uri(
                httpretty.GET,
                self._url(),
                body="schema=1\nversion=1.27.0\n",
                status=200,
            )
            manifest = update_check.fetch_latest_manifest(create_requests_session())
        assert manifest["version"] == "1.27.0"

    def test_follows_redirect(self):
        """The ``latest`` alias 302-redirects to a concrete version manifest."""
        import httpretty

        from cloudsmith_cli.core.session import create_requests_session

        concrete = self._url().replace("latest", "1.27.0")
        with httpretty.enabled(allow_net_connect=False):
            httpretty.register_uri(
                httpretty.GET,
                self._url(),
                status=302,
                location=concrete,
            )
            httpretty.register_uri(
                httpretty.GET,
                concrete,
                body="version=1.27.0\n",
                status=200,
            )
            manifest = update_check.fetch_latest_manifest(create_requests_session())
        assert manifest["version"] == "1.27.0"

    def test_missing_version_raises(self):
        import httpretty

        from cloudsmith_cli.core.session import create_requests_session

        with httpretty.enabled(allow_net_connect=False):
            httpretty.register_uri(
                httpretty.GET, self._url(), body="schema=1\n", status=200
            )
            with pytest.raises(ValueError):
                update_check.fetch_latest_manifest(create_requests_session())

    def test_http_error_raises(self):
        import httpretty

        from cloudsmith_cli.core.session import create_requests_session

        with httpretty.enabled(allow_net_connect=False):
            httpretty.register_uri(httpretty.GET, self._url(), status=404)
            with pytest.raises(requests.RequestException):
                update_check.fetch_latest_manifest(create_requests_session(retries=0))


class TestRunBackgroundCheck:
    def test_records_on_success(self, state_path):
        update_check.run_background_check(
            _FakeSession(version_str=NEWER_VERSION), now=NOW
        )
        assert _read_state(state_path)["latest_version"] == NEWER_VERSION
        assert _read_state(state_path)["last_check_at"] == NOW

    def test_swallows_network_failure_and_records_nothing(self, state_path):
        # Must not raise, and must not create the state file.
        update_check.run_background_check(_FakeSession(fails=True), now=NOW)
        assert not os.path.exists(state_path)


class TestNoticeSuppressed:
    @pytest.fixture
    def _tty(self, monkeypatch):
        monkeypatch.setattr(update_check, "stderr_is_tty", lambda: True)

    @pytest.mark.parametrize("fmt", ["json", "pretty_json"])
    def test_machine_output_suppresses(self, fmt, _tty):
        assert update_check.notice_suppressed(fmt, None) is True

    def test_non_tty_suppresses(self, monkeypatch):
        monkeypatch.setattr(update_check, "stderr_is_tty", lambda: False)
        assert update_check.notice_suppressed("pretty", None) is True

    @pytest.mark.parametrize("cmd", ["mcp", "update", "upgrade"])
    def test_suppressed_subcommands(self, cmd, _tty):
        assert update_check.notice_suppressed("pretty", cmd) is True

    def test_not_suppressed_for_normal_interactive_command(self, _tty):
        assert update_check.notice_suppressed("pretty", "list") is False


class TestFinishAndNotify:
    """Join-then-notify at command close."""

    def test_notifies_and_bumps_when_behind(self, state_path, capsys):
        _write_state(
            state_path, last_check_at=NOW - (DAY * 2), latest_version=NEWER_VERSION
        )
        update_check._finish_and_notify(None, now=NOW)
        err = capsys.readouterr().err
        assert "new version" in err.lower()
        assert NEWER_VERSION in err
        assert _read_state(state_path)["last_check_at"] == NOW

    def test_silent_when_up_to_date(self, state_path, capsys):
        _write_state(state_path, last_check_at=NOW, latest_version=CURRENT_VERSION)
        update_check._finish_and_notify(None, now=NOW)
        assert capsys.readouterr().err == ""

    def test_joins_thread_before_reading_state(self, state_path, capsys):
        """A thread that writes a newer version is joined, then the notice fires."""
        import threading

        _write_state(state_path, last_check_at=NOW - (DAY * 2))

        def writer():
            update_check.record_check(NEWER_VERSION, now=NOW)

        thread = threading.Thread(target=writer)
        thread.start()
        update_check._finish_and_notify(thread, now=NOW + 1)
        err = capsys.readouterr().err
        assert NEWER_VERSION in err
