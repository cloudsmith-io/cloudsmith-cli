import uuid

import pytest

from cloudsmith_cli.core.usage import identity, state


def _is_uuid(value):
    return str(uuid.UUID(value)) == value


def test_default_is_anonymous_per_run_and_writes_nothing(usage_state_dir):
    first = identity.resolve(ephemeral=False, install_id_enabled=False)
    second = identity.resolve(ephemeral=False, install_id_enabled=False)
    assert first.anonymous and second.anonymous
    assert first.distinct_id != second.distinct_id and _is_uuid(first.distinct_id)
    assert state.read() == {}


def test_ephemeral_never_persists_even_when_enabled(usage_state_dir):
    ident = identity.resolve(ephemeral=True, install_id_enabled=True)
    assert ident.anonymous and not ident.persisted
    assert "install_id" not in state.read()


def test_install_id_persists_and_first_run_flag(usage_state_dir):
    first = identity.resolve(ephemeral=False, install_id_enabled=True)
    second = identity.resolve(ephemeral=False, install_id_enabled=True)
    assert first.first_run and not second.first_run
    assert first.distinct_id == second.distinct_id
    assert not first.anonymous and first.persisted
    assert state.read()["install_id"] == first.distinct_id


@pytest.mark.parametrize(
    "stored", ["hello@example.com", "6F9619FF-8B86-D011-B42D-00CF4FC964FF", 7]
)
def test_a_stored_id_that_is_not_a_uuid_is_replaced(usage_state_dir, stored):
    # A hand-edited telemetry.json must not put arbitrary text in distinct_id.
    state.write({"install_id": stored, "notice_version": 1})
    ident = identity.resolve(ephemeral=False, install_id_enabled=True)
    assert _is_uuid(ident.distinct_id) and ident.first_run and ident.persisted
    assert state.read()["install_id"] == ident.distinct_id
    assert state.read()["notice_version"] == 1


def test_reset_deletes_the_id_and_keeps_other_state(usage_state_dir, monkeypatch):
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_INSTALL_ID", "1")
    old = identity.resolve(ephemeral=False, install_id_enabled=True).distinct_id
    state.write({"notice_version": 1})
    identity.reset()
    assert "install_id" not in state.read()
    assert state.read()["notice_version"] == 1
    again = identity.resolve(ephemeral=False, install_id_enabled=True)
    assert again.first_run and again.distinct_id != old


def test_reset_never_mints_an_id(usage_state_dir, monkeypatch):
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_INSTALL_ID", "1")
    identity.reset()
    assert state.read() == {}


def test_reset_raises_when_delete_fails(usage_state_dir, monkeypatch):
    identity.resolve(ephemeral=False, install_id_enabled=True)
    monkeypatch.setattr(state, "delete", lambda: False)
    with pytest.raises(identity.IdentityResetError):
        identity.reset()


def test_reset_raises_when_restoring_other_state_fails(usage_state_dir, monkeypatch):
    state.write({"install_id": "x", "notice_version": 1})
    monkeypatch.setattr(state, "write", lambda updates: False)
    with pytest.raises(identity.IdentityResetError):
        identity.reset()
