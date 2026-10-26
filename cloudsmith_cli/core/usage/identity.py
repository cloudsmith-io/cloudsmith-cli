# Copyright 2026 Cloudsmith Ltd
"""Which ``distinct_id`` an event carries."""

import time
import uuid
from dataclasses import dataclass

from . import state


class IdentityResetError(Exception):
    """The stored install ID could not be removed or other state restored."""


@dataclass(frozen=True)
class Identity:
    distinct_id: str
    anonymous: bool
    first_run: bool
    persisted: bool


def _one_off():
    return Identity(str(uuid.uuid4()), anonymous=True, first_run=False, persisted=False)


def _is_install_id(value):
    # Only the canonical form uuid4() writes; a hand-edited file must not put
    # arbitrary text into distinct_id.
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def resolve(*, ephemeral, install_id_enabled):
    if ephemeral or not install_id_enabled:
        return _one_off()
    # Read and create under one lock, so two first runs agree on one ID.
    with state.locked() as ok:
        if not ok:
            return _one_off()
        current = state.read().get("install_id")
        if _is_install_id(current):
            return Identity(current, anonymous=False, first_run=False, persisted=True)
        new_id = str(uuid.uuid4())
        if state.write({"install_id": new_id, "created_at": int(time.time())}):
            return Identity(new_id, anonymous=False, first_run=True, persisted=True)
    return _one_off()


def reset():
    """Delete the stored install ID.

    resolve() creates a new random one on the next run, so a deleted ID never
    re-links. Holds the state lock throughout, so a concurrent run cannot
    write its old copy of the file (and the ID) back.
    """
    with state.locked() as ok:
        if not ok:
            raise IdentityResetError("telemetry state is locked by another process")
        data = state.read()
        data.pop("install_id", None)
        data.pop("created_at", None)
        if not state.delete():
            raise IdentityResetError("could not remove the stored install ID")
        if data and not state.write(data):
            raise IdentityResetError(
                "removed the install ID but could not restore other telemetry state"
            )


def forget():
    """Delete a stored install ID after an opt-out; silent, never raises.

    Writes nothing when no ID is stored, so an opted-out run creates no file.
    """
    data = state.read()
    if "install_id" not in data and "created_at" not in data:
        return
    try:
        reset()
    except IdentityResetError:
        return
