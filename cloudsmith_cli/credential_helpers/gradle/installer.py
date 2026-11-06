# Copyright 2026 Cloudsmith Ltd
"""Apply the Cloudsmith Gradle plugin to every Gradle build of the user."""

from __future__ import annotations

import os
import re
import shutil
from functools import partial
from pathlib import Path

from .. import maven_tools
from ..maven_tools import REPOSITORY_URL, ConfigFileInstaller

INIT_SCRIPT_NAME = "cloudsmith.init.gradle.kts"
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
_PROBE_INIT_SCRIPT = (
    'println("CLOUDSMITH_GRADLE_USER_HOME=${gradle.gradleUserHomeDir.absolutePath}")\n'
)
_USER_HOME_LINE = re.compile(r"^CLOUDSMITH_GRADLE_USER_HOME=(.+)$", re.MULTILINE)


def _reported_user_home(gradle: str, cwd: Path) -> Path | None:
    """Return the Gradle user home that an init script prints when Gradle runs in ``cwd``."""
    # Gradle looks for a settings file in the parent directories when there is none here.
    (cwd / "settings.gradle").write_text("", encoding="utf-8")
    probe = cwd / "probe.init.gradle"
    probe.write_text(_PROBE_INIT_SCRIPT, encoding="utf-8")
    output = maven_tools.tool_output(
        [gradle, "-q", "--offline", "--no-daemon", "-I", str(probe), "help"], cwd
    )
    match = _USER_HOME_LINE.search(output)
    return Path(match.group(1)) if match else None


class GradleInstaller(ConfigFileInstaller):
    name = "gradle"
    summary = "Gradle plugin that gets credentials from the Cloudsmith CLI"
    artifact_path = "io/cloudsmith/cloudsmith-gradle-plugin"

    def path(self) -> Path:
        gradle_user_home = os.environ.get("GRADLE_USER_HOME")
        base = Path(gradle_user_home) if gradle_user_home else Path.home() / ".gradle"
        return base / "init.d" / INIT_SCRIPT_NAME

    def tool_path(self) -> Path:
        """Return the init script in the Gradle user home that ``gradle`` reports."""
        gradle = shutil.which("gradle")
        if gradle is None:
            return self.path()
        user_home = maven_tools.ask_outside_projects(
            partial(_reported_user_home, gradle),
            "The Gradle user home is a relative path, so each build looks for the "
            "init script in its own directory. Set an absolute path for "
            "gradle.user.home.",
        )
        return user_home / "init.d" / INIT_SCRIPT_NAME if user_home else self.path()

    def render(self, version: str) -> str:
        return INIT_SCRIPT.format(repository_url=REPOSITORY_URL, version=version)
