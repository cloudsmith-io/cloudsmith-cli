# Copyright 2026 Cloudsmith Ltd
"""Apply the Cloudsmith Gradle plugin to every Gradle build of the user."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..maven_tools import (
    REPOSITORY_URL,
    ConfigFileInstaller,
    InstallOptionError,
    latest_version,
)

if TYPE_CHECKING:
    import requests

INIT_SCRIPT = """\
// Written by `cloudsmith credential-helper install gradle`.
initscript {{
    repositories {{
        maven {{ url = uri("{repository_url}") }}
    }}
    dependencies {{
        classpath("io.cloudsmith:cloudsmith-gradle-plugin:{version}")
    }}
}}

beforeSettings {{
    pluginManager.apply(io.cloudsmith.gradle.CloudsmithPlugin::class.java)
}}
"""

SETTINGS_PLUGIN = """\
--local is not supported for gradle. To set up one build, add the plugin to \
settings.gradle.kts:

pluginManagement {{
    repositories {{
        maven {{ url = uri("{repository_url}") }}
        gradlePluginPortal()
    }}
}}

plugins {{
    id("io.cloudsmith.gradle-plugin") version "{version}"
}}
"""


class GradleInstaller(ConfigFileInstaller):
    name = "gradle"
    summary = "Gradle plugin that gets credentials from the Cloudsmith CLI"
    artifact_path = "io/cloudsmith/cloudsmith-gradle-plugin"

    def path(self) -> Path:
        gradle_user_home = os.environ.get("GRADLE_USER_HOME")
        base = Path(gradle_user_home) if gradle_user_home else Path.home() / ".gradle"
        return base / "init.d" / "cloudsmith.init.gradle.kts"

    def install(
        self,
        *,
        local: bool = False,
        session: requests.Session | None = None,
        **options,
    ) -> list[str]:
        if local:
            # Gradle has no init scripts for one build, and a script edit of the
            # build's settings file could break it.
            raise InstallOptionError(
                SETTINGS_PLUGIN.format(
                    repository_url=REPOSITORY_URL,
                    version=latest_version(self.artifact_path, session),
                )
            )
        return super().install(session=session, **options)

    def local_path(self) -> Path:
        raise InstallOptionError("--local is not supported for gradle.")

    def render(self, version: str) -> str:
        return INIT_SCRIPT.format(repository_url=REPOSITORY_URL, version=version)
