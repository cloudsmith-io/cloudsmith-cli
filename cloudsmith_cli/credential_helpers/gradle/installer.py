# Copyright 2026 Cloudsmith Ltd
"""Apply the Cloudsmith Gradle plugin to every Gradle build of the user."""

from __future__ import annotations

import os
import re
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


class GradleInstaller(ConfigFileInstaller):
    name = "gradle"
    summary = "Gradle plugin that gets credentials from the Cloudsmith CLI"
    artifact_path = "io/cloudsmith/cloudsmith-gradle-plugin"
    tool = "gradle"
    reported = "Gradle user home"
    relative_message = (
        "The Gradle user home is a relative path, so each build looks for the init "
        "script in its own directory. Set an absolute path for gradle.user.home."
    )

    def path(self) -> Path:
        gradle_user_home = os.environ.get("GRADLE_USER_HOME")
        base = Path(gradle_user_home) if gradle_user_home else Path.home() / ".gradle"
        return base / "init.d" / INIT_SCRIPT_NAME

    def reported_path(self, executable: str, cwd: Path) -> Path | None:
        """Return the init script in the Gradle user home that an init script prints."""
        probe = cwd / "probe.init.gradle"
        probe.write_text(_PROBE_INIT_SCRIPT, encoding="utf-8")
        output = maven_tools.tool_output(
            [executable, "-q", "--offline", "--no-daemon", "-I", str(probe), "help"],
            cwd,
        )
        match = _USER_HOME_LINE.search(output)
        return cwd / match.group(1) / "init.d" / INIT_SCRIPT_NAME if match else None

    def render(self, version: str) -> str:
        return INIT_SCRIPT.format(repository_url=REPOSITORY_URL, version=version)
