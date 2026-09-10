# Copyright 2026 Cloudsmith Ltd
"""Tests for cloudsmith_cli.core.update_check.

Two decoupled rhythms are exercised: the daily *fetch* (gated by
``last_checked_at`` + the disable controls) and the *notice* (gated by the
invariant ``last_notified_at < last_checked_at`` + presentation suppressors).
The network is stubbed throughout via a fake requests session.
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


def _write_state(path, *, last_checked_at=None, last_notified_at=None, latest_version):
    state = {"latest_version": latest_version}
    if last_checked_at is not None:
        state["last_checked_at"] = last_checked_at
    if last_notified_at is not None:
        state["last_notified_at"] = last_notified_at
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _read_state(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class _FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"status {self.status}")


class _FakeSession:
    """A stand-in requests session recording whether ``get`` was called."""

    def __init__(self, *, version_str=CURRENT_VERSION, fails=False):
        self.version = version_str
        self.fails = fails
        self.called = False

    def get(self, url, timeout=None):
        self.called = True
        if self.fails:
            raise requests.ConnectionError("network down")
        return _FakeResponse(f"schema=1\nversion={self.version}\n")


def _run(session, *, now=NOW, no_check_flag=False, config_value=True, env=None):
    """Drive the real fetch decision synchronously with a fake session.

    Mirrors the fetch half of ``arm``: if a check is due, either bump (already
    behind) or run the real ``run_background_check``. Returns the session.
    """
    env = {} if env is None else env
    if not update_check.should_check_for_update(
        no_check_flag=no_check_flag, config_value=config_value, env=env, now=now
    ):
        return session
    if update_check.newer_version_known(update_check.read_latest_version()):
        update_check.record_check(update_check.read_latest_version(), now=now)
        return session
    update_check.run_background_check(session, now=now)
    return session


# ---------------------------------------------------------------------------
# The daily fetch decision + state
# ---------------------------------------------------------------------------


class TestFetchDecision:
    def test_no_state_file_triggers_fetch_and_creates_file(self, state_path):
        assert not os.path.exists(state_path)
        session = _run(_FakeSession(version_str=CURRENT_VERSION))
        assert session.called is True
        assert os.path.exists(state_path)
        assert _read_state(state_path)["last_checked_at"] == NOW

    def test_stale_state_triggers_fetch_and_updates_file(self, state_path):
        _write_state(
            state_path, last_checked_at=NOW - (DAY * 3), latest_version=CURRENT_VERSION
        )
        session = _run(_FakeSession(version_str=CURRENT_VERSION))
        assert session.called is True
        assert _read_state(state_path)["last_checked_at"] == NOW

    def test_recent_state_skips_fetch_and_leaves_file(self, state_path):
        recent = NOW - 60.0
        _write_state(state_path, last_checked_at=recent, latest_version=CURRENT_VERSION)
        before = os.stat(state_path).st_mtime_ns
        session = _run(_FakeSession(version_str=CURRENT_VERSION))
        assert session.called is False
        assert _read_state(state_path)["last_checked_at"] == recent
        assert os.stat(state_path).st_mtime_ns == before

    def test_stale_but_newer_known_bumps_without_fetch(self, state_path):
        """Already behind → bump last_checked_at (re-arm notice), no fetch."""
        _write_state(
            state_path, last_checked_at=NOW - (DAY * 3), latest_version=NEWER_VERSION
        )
        session = _run(_FakeSession(version_str=NEWER_VERSION))
        assert session.called is False
        after = _read_state(state_path)
        assert after["last_checked_at"] == NOW
        assert after["latest_version"] == NEWER_VERSION

    def test_no_state_file_failed_fetch_does_not_create_file(self, state_path):
        assert not os.path.exists(state_path)
        session = _run(_FakeSession(fails=True))
        assert session.called is True
        assert not os.path.exists(state_path)

    def test_stale_state_failed_fetch_does_not_update_file(self, state_path):
        stale = NOW - (DAY * 3)
        _write_state(state_path, last_checked_at=stale, latest_version=CURRENT_VERSION)
        session = _run(_FakeSession(fails=True))
        assert session.called is True
        assert _read_state(state_path)["last_checked_at"] == stale


# ---------------------------------------------------------------------------
# The notice invariant + daily re-nag
# ---------------------------------------------------------------------------


class TestShouldNotify:
    def test_true_when_behind_and_checked_since_notify(self, state_path):
        _write_state(
            state_path,
            last_checked_at=NOW,
            last_notified_at=NOW - 10,
            latest_version=NEWER_VERSION,
        )
        assert update_check.should_notify() is True

    def test_false_when_up_to_date(self, state_path):
        _write_state(
            state_path,
            last_checked_at=NOW,
            last_notified_at=0,
            latest_version=CURRENT_VERSION,
        )
        assert update_check.should_notify() is False

    def test_false_when_already_notified_for_this_check(self, state_path):
        """last_notified_at == last_checked_at → disarmed until the next check."""
        _write_state(
            state_path,
            last_checked_at=NOW,
            last_notified_at=NOW,
            latest_version=NEWER_VERSION,
        )
        assert update_check.should_notify() is False

    def test_true_when_never_notified(self, state_path):
        _write_state(state_path, last_checked_at=NOW, latest_version=NEWER_VERSION)
        assert update_check.should_notify() is True

    def test_false_when_no_state(self, state_path):
        assert update_check.should_notify() is False

    def test_current_version_override(self, state_path):
        state = {
            "latest_version": "1.5.0",
            "last_checked_at": NOW,
            "last_notified_at": 0,
        }
        assert update_check.should_notify(state, current_version="1.0.0") is True
        assert update_check.should_notify(state, current_version="2.0.0") is False


class TestDailyRenag:
    """The full notify → disarm → re-arm-next-day cycle."""

    def _notify_cycle(self, state_path, now):
        """Mirror _finish_and_notify's notify branch (assuming not suppressed)."""
        state = update_check.read_cached_state()
        if update_check.should_notify(state):
            update_check.record_notified(now=now)
            return True
        return False

    def test_notify_then_throttle_then_renag(self, state_path):
        # Behind, fetched today, never notified → notify.
        _write_state(state_path, last_checked_at=NOW, latest_version=NEWER_VERSION)
        assert self._notify_cycle(state_path, NOW) is True
        assert _read_state(state_path)["last_notified_at"] == NOW

        # Same check, later the same run/day → disarmed.
        assert self._notify_cycle(state_path, NOW + 60) is False

        # A day passes: a fresh check bumps last_checked_at → re-armed.
        update_check.record_check(NEWER_VERSION, now=NOW + DAY + 60)
        assert self._notify_cycle(state_path, NOW + DAY + 120) is True


class TestMissedWarningRegression:
    """A fetch that could not notify must not consume the notice budget."""

    def test_suppressed_fetch_does_not_advance_notified(self, state_path):
        # Cold start: a fetch runs (as it would under -F json / non-TTY) and
        # discovers a newer version, advancing last_checked_at only.
        _run(_FakeSession(version_str=NEWER_VERSION), now=NOW)
        state = _read_state(state_path)
        assert state["last_checked_at"] == NOW
        assert state["latest_version"] == NEWER_VERSION
        assert "last_notified_at" not in state

        # A later interactive run (no new fetch needed) still notifies, because
        # last_notified_at (absent → 0) < last_checked_at.
        assert update_check.should_notify() is True


class TestShouldCheckForUpdate:
    def test_due_when_stale_even_if_behind(self, state_path):
        _write_state(
            state_path, last_checked_at=NOW - (DAY * 2), latest_version=NEWER_VERSION
        )
        assert (
            update_check.should_check_for_update(
                no_check_flag=False, config_value=True, env={}, now=NOW
            )
            is True
        )

    def test_not_due_when_recent(self, state_path):
        _write_state(
            state_path, last_checked_at=NOW - 60.0, latest_version=CURRENT_VERSION
        )
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
    """The --no-check-update flag, env vars and config key suppress the fetch."""

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
    def test_record_check_preserves_notified(self, state_path):
        _write_state(
            state_path,
            last_checked_at=1.0,
            last_notified_at=500.0,
            latest_version=OLDER_VERSION,
        )
        update_check.record_check(NEWER_VERSION, now=NOW)
        state = _read_state(state_path)
        assert state["last_checked_at"] == NOW
        assert state["latest_version"] == NEWER_VERSION
        assert state["last_notified_at"] == 500.0

    def test_record_notified_preserves_check(self, state_path):
        _write_state(state_path, last_checked_at=NOW, latest_version=NEWER_VERSION)
        update_check.record_notified(now=NOW + 5)
        state = _read_state(state_path)
        assert state["last_notified_at"] == NOW + 5
        assert state["last_checked_at"] == NOW
        assert state["latest_version"] == NEWER_VERSION

    def test_read_missing_file_returns_none(self, state_path):
        assert update_check.read_last_check_time() is None
        assert update_check.read_last_notified_time() is None
        assert update_check.read_latest_version() is None
        assert update_check.read_cached_state() == {}

    def test_read_corrupt_file_returns_empty(self, state_path):
        with open(state_path, "w", encoding="utf-8") as f:
            f.write("not json")
        assert update_check.read_cached_state() == {}
        assert update_check.read_last_check_time() is None

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
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        path = str(blocker / "update_check.json")
        monkeypatch.setattr(update_check, "get_state_file_path", lambda: path)
        update_check.record_check(CURRENT_VERSION, now=NOW)  # must not raise
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
                httpretty.GET, self._url(), status=302, location=concrete
            )
            httpretty.register_uri(
                httpretty.GET, concrete, body="version=1.27.0\n", status=200
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
        assert _read_state(state_path)["last_checked_at"] == NOW

    def test_swallows_network_failure_and_records_nothing(self, state_path):
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
    """Join-then-notify at command close, honouring presentation suppressors."""

    class _Opts:
        def __init__(self, output="pretty"):
            self.output = output

    @pytest.fixture(autouse=True)
    def _tty(self, monkeypatch):
        monkeypatch.setattr(update_check, "stderr_is_tty", lambda: True)

    def test_notifies_and_stamps_when_behind(self, state_path, capsys):
        _write_state(state_path, last_checked_at=NOW, latest_version=NEWER_VERSION)
        update_check._finish_and_notify(None, self._Opts(), "list", now=NOW + 1)
        err = capsys.readouterr().err
        assert "new version" in err.lower()
        assert NEWER_VERSION in err
        assert _read_state(state_path)["last_notified_at"] == NOW + 1

    def test_silent_and_untouched_when_suppressed(self, state_path, capsys):
        """JSON output suppresses the notice and does not stamp last_notified."""
        _write_state(state_path, last_checked_at=NOW, latest_version=NEWER_VERSION)
        update_check._finish_and_notify(None, self._Opts("json"), "list", now=NOW + 1)
        assert capsys.readouterr().err == ""
        assert "last_notified_at" not in _read_state(state_path)

    def test_silent_when_up_to_date(self, state_path, capsys):
        _write_state(state_path, last_checked_at=NOW, latest_version=CURRENT_VERSION)
        update_check._finish_and_notify(None, self._Opts(), "list", now=NOW)
        assert capsys.readouterr().err == ""

    def test_joins_thread_before_reading_state(self, state_path, capsys):
        import threading

        _write_state(state_path, last_checked_at=1.0, latest_version=CURRENT_VERSION)

        def writer():
            update_check.record_check(NEWER_VERSION, now=NOW)

        thread = threading.Thread(target=writer)
        thread.start()
        update_check._finish_and_notify(thread, self._Opts(), "list", now=NOW + 1)
        assert NEWER_VERSION in capsys.readouterr().err
