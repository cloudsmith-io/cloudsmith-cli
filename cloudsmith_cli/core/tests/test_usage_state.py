import json
import os

from cloudsmith_cli.core.usage import state


def test_read_missing_or_corrupt_is_empty(usage_state_dir):
    assert state.read() == {}
    with open(state.state_path(), "w") as f:
        f.write("{not json")
    assert state.read() == {}


def test_write_merges_and_uses_0600(usage_state_dir):
    assert state.write({"notice_version": 1}) is True
    assert state.write({"last_failure_at": 5.0}) is True
    assert state.read() == {"notice_version": 1, "last_failure_at": 5.0}
    assert oct(os.stat(state.state_path()).st_mode & 0o777) == "0o600"
    with open(state.state_path()) as f:
        assert json.load(f)["notice_version"] == 1


def test_write_failure_returns_false(usage_state_dir, monkeypatch):
    monkeypatch.setattr(state, "state_path", lambda: "/nonexistent/dir/telemetry.json")
    monkeypatch.setattr(
        os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    assert state.write({"x": 1}) is False


def test_writable_true_for_a_writable_dir(usage_state_dir):
    assert state.writable() is True
    assert not os.path.exists(state.state_path())


def test_writable_walks_up_to_the_nearest_existing_dir(usage_state_dir, monkeypatch):
    missing = os.path.join(str(usage_state_dir), "not", "yet")
    monkeypatch.setattr(state, "config_dir", lambda: missing)
    assert state.writable() is True
    assert not os.path.exists(missing)


def test_writable_false_when_not_accessible(usage_state_dir, monkeypatch):
    monkeypatch.setattr(os, "access", lambda *a, **k: False)
    assert state.writable() is False


def _other_process(usage_state_dir, code):
    """Run ``code`` in a second process using the same state dir.

    It prints ``ready`` just before the state call under test, then the
    call's result.
    """
    import subprocess
    import sys

    script = (
        "from cloudsmith_cli.core.usage import identity, state\n"
        f"state.config_dir = lambda: {str(usage_state_dir)!r}\n"
        "print('ready', flush=True)\n"
        f"print(repr({code}), flush=True)\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
    )


def test_a_concurrent_write_never_restores_a_reset_install_id(usage_state_dir):
    import time

    from cloudsmith_cli.core.usage import identity

    state.write({"install_id": "a" * 8, "notice_version": 2})
    with state.locked() as ok:
        assert ok
        other = _other_process(usage_state_dir, "state.write({'last_failure_at': 1})")
        assert other.stdout.readline().strip() == "ready"
        time.sleep(0.05)  # the other process is now waiting for the lock
        identity.reset()
    assert other.stdout.readline().strip() == "True"
    other.wait(10)
    # The other process read the file after the reset, not before it.
    assert state.read() == {"notice_version": 2, "last_failure_at": 1}


def test_writes_give_up_rather_than_wait_on_a_held_lock(usage_state_dir, monkeypatch):
    import pytest

    from cloudsmith_cli.core.usage import identity

    monkeypatch.setattr(state, "LOCK_TIMEOUT_SECONDS", 0.1)
    handle = state._acquire()  # held as if by another process
    try:
        assert state.write({"x": 1}) is False
        assert (
            identity.resolve(ephemeral=False, install_id_enabled=True).persisted
            is False
        )
        with pytest.raises(identity.IdentityResetError):
            identity.reset()
    finally:
        state._unlock(handle)
    assert state.read() == {}


def test_locked_is_reentrant(usage_state_dir):
    with state.locked() as outer:
        with state.locked() as inner:
            assert outer and inner
            assert state.write({"x": 1}) is True
    assert state.read() == {"x": 1}
