# Copyright 2026 Cloudsmith Ltd
"""Maven shell plugin.

Maven has no credential helper, so we inject an ephemeral ``settings.xml`` via
``mvn -s`` for the duration of a single invocation.  The file carries a
``<server>`` (matched by id to both our injected download profile and the
user's ``distributionManagement``) plus an active profile whose repositories
point at the Cloudsmith download CDN — so dependency resolution works with no
``pom.xml`` edits.  Upload (deploy) reuses the same ``<server>`` credentials;
its URL comes from the user's ``distributionManagement``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from xml.sax.saxutils import escape

from ...templates import render
from ..common import repo_path_segment
from .config import PluginEntry
from .plugin import ProvisionResult

_SKIP_AUTH_ARGS = ["--help", "--version", "-v", "help"]
_SETTINGS_TEMPLATE = "maven_settings.xml.tmpl"


def download_url(owner: str, repo: str, cdn_host: str) -> str:
    """Return the Maven download (dependency-resolution) repository URL."""
    return f"https://{cdn_host}/basic/{repo_path_segment(owner, repo, cdn_host)}/maven/"


def upload_url(owner: str, repo: str, upload_host: str) -> str:
    """Return the native Maven upload (distributionManagement) URL."""
    return f"https://{upload_host}/{repo_path_segment(owner, repo, upload_host)}/"


def build_settings_xml(
    owner: str, repo: str, token: str, cdn_host: str, server_id: str
) -> str:
    """Return a Maven ``settings.xml`` body for the given repo + credentials."""
    return render(
        _SETTINGS_TEMPLATE,
        server_id=escape(server_id),
        token=escape(token),
        url=escape(download_url(owner, repo, cdn_host)),
    )


class MavenPlugin:
    """Provisions an ephemeral ``settings.xml`` and runs ``mvn`` with ``-s``."""

    name = "maven"
    binary_name = "mvn"

    def skip_auth_args(self) -> list[str]:
        """Args for which Maven needs no Cloudsmith credentials."""
        return list(_SKIP_AUTH_ARGS)

    def provision(
        self, entry: PluginEntry, token: str, args: list[str]
    ) -> ProvisionResult:
        """Write a 0600 ``settings.xml`` and return ``-s <path>`` to prepend.

        Atomic: if writing fails the temp dir is removed before re-raising, so
        a partial provisioning never leaks a directory.
        """
        temp_dir = tempfile.mkdtemp(prefix="cloudsmith-maven-")
        written = False
        try:
            settings_path = os.path.join(temp_dir, "settings.xml")
            content = build_settings_xml(
                owner=entry.owner,
                repo=entry.repo,
                token=token,
                cdn_host=entry.cdn_host,
                server_id=entry.registry_id,
            )
            with open(settings_path, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(settings_path, 0o600)
            written = True
            return ProvisionResult(
                prepend_args=["-s", settings_path],
                temp_dirs=[temp_dir],
            )
        finally:
            if not written:
                shutil.rmtree(temp_dir, ignore_errors=True)
