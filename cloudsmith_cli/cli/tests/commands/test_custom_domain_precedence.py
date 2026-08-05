# Copyright 2026 Cloudsmith Ltd
"""Tests for custom-domain precedence and the record fields it ranks on.

Those fields have to survive the on-disk cache: a run served from the cache
must rank domains identically to the run that populated it.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from ....credential_helpers.backends import BackendKind
from ....credential_helpers.custom_domains import (
    CustomDomain,
    _record_from_payload,
    get_format_domains,
    read_cache,
    write_cache,
)
from ....credential_helpers.default_domains import DomainType


def _domain(
    host, *, backend_kind=None, primary=True, created_at="2025-01-01T00:00:00Z"
):
    """Build a CustomDomain record for a test."""
    return CustomDomain(
        host=host,
        backend_kind=backend_kind,
        enabled=True,
        validated=True,
        org="acme",
        domain_type=(
            DomainType.DOWNLOAD if backend_kind is None else DomainType.NATIVE_API
        ),
        primary=primary,
        created_at=created_at,
    )


def test_format_domains_are_returned_in_precedence_order():
    """The host Cloudsmith treats as active comes first.

    Callers take the first host, so the order is the answer: primary beats
    secondary, and the oldest breaks a tie between equals.
    """
    records = [
        _domain("second.acme.com", backend_kind=BackendKind.DOCKER, primary=False),
        _domain(
            "third.acme.com",
            backend_kind=BackendKind.DOCKER,
            created_at="2026-01-01T00:00:00Z",
        ),
        _domain(
            "first.acme.com",
            backend_kind=BackendKind.DOCKER,
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    with patch(
        "cloudsmith_cli.credential_helpers.custom_domains.get_custom_domains",
        return_value=records,
    ):
        hosts = get_format_domains("acme", BackendKind.DOCKER)

    assert hosts == ["first.acme.com", "third.acme.com", "second.acme.com"]


def test_domain_with_no_creation_time_ranks_last_not_first():
    """An unknown creation time is a last resort, not the oldest domain."""
    records = [
        _domain("nodate.acme.com", backend_kind=BackendKind.DOCKER, created_at=None),
        _domain(
            "dated.acme.com",
            backend_kind=BackendKind.DOCKER,
            created_at="2020-01-01T00:00:00Z",
        ),
    ]

    with patch(
        "cloudsmith_cli.credential_helpers.custom_domains.get_custom_domains",
        return_value=records,
    ):
        hosts = get_format_domains("acme", BackendKind.DOCKER)

    assert hosts == ["dated.acme.com", "nodate.acme.com"]


def test_precedence_fields_survive_the_api_and_the_cache(tmp_path):
    """A cached run must rank domains the way the fetching run did.

    The SDK deserialises ``created_at`` into a datetime that JSON cannot hold,
    so it is normalised on the way in; dropping any of these fields on the way
    to disk would silently fall back to API order for the whole seven-day TTL.
    """
    record = _record_from_payload(
        {
            "host": "dl.acme.com",
            "enabled": True,
            "validated": True,
            "primary": False,
            "repository": {"name": "Prod", "slug": "prod"},
            "created_at": datetime(2025, 3, 4, 9, 22, 30, tzinfo=timezone.utc),
        },
        "acme",
    )

    assert record.created_at.startswith("2025-03-04T09:22:30")
    assert record.primary is False
    assert record.repository == "prod"

    cache_path = tmp_path / "acme.json"
    write_cache(cache_path, [record])

    assert read_cache(cache_path) == [record]
