# Copyright 2026 Cloudsmith Ltd
"""The ``settings.xml`` a wrapped ``mvn`` run is handed.

Maven has no credential-helper protocol, so credentials are injected as a
generated ``settings.xml`` passed with ``mvn -s`` rather than written into
``~/.m2``.  It carries an active profile, authored entirely by us, whose
repositories point at the Cloudsmith download CDN — so dependency resolution
works with no ``pom.xml`` edits — and one ``<server>`` holding the token.

That server's id is the same one ``distributionManagement`` names for
publishing, so it is deliberately stable and guessable (``cloudsmith`` by
default, or ``--server-id``): a team shares one ``pom.xml``.  Maven matches a
server's credentials to a repository by id alone, with no host check, so a
``pom.xml`` declaring a repository under that id receives the token — the same
exposure as the ``~/.m2/settings.xml`` every Maven user already keeps.  Set
``--server-id`` to something unguessable to close it.
"""

from __future__ import annotations

import os
from xml.sax.saxutils import escape

from ...templates import render
from ..common import repo_path_segment
from .config import Binding

SETTINGS_FILENAME = "settings.xml"

_SETTINGS_TEMPLATE = "maven_settings.xml.tmpl"


def _cloudsmith_url(host: str, *parts: str) -> str:
    """Join the non-empty *parts* into a trailing-slash URL under *host*."""
    path = "/".join(part for part in parts if part)
    return f"https://{host}/{path}/" if path else f"https://{host}/"


def download_url(owner: str, repo: str, host: str) -> str:
    """Return the Maven download (dependency-resolution) repository URL."""
    return _cloudsmith_url(host, "basic", repo_path_segment(owner, repo, host), "maven")


def upload_url(owner: str, repo: str, host: str) -> str:
    """Return the native Maven upload (distributionManagement) URL."""
    return _cloudsmith_url(host, repo_path_segment(owner, repo, host))


def build_settings_xml(binding: Binding, token: str) -> str:
    """Return the ``settings.xml`` body for *binding* and *token*."""
    return render(
        _SETTINGS_TEMPLATE,
        server_id=escape(binding.server_id),
        token=escape(token),
        url=escape(download_url(binding.owner, binding.repo, binding.download_host)),
    )


def write_settings(directory: str, content: str) -> str:
    """Write *content* as a mode-0600 ``settings.xml`` in *directory*.

    Opened with the mode applied on creation, so the token is never briefly
    world-readable — an ``open()`` at the process umask followed by ``chmod``
    leaves a window where it is.
    """
    path = os.path.join(directory, SETTINGS_FILENAME)
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path
