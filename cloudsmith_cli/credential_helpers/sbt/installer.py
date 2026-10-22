# Copyright 2026 Cloudsmith Ltd
"""Add the Cloudsmith sbt plugin to every sbt 1 build of the user."""

from __future__ import annotations

from pathlib import Path

from ..maven_tools import REPOSITORY_URL, ConfigFileInstaller, ProjectNotFound

GLOBAL_PLUGIN = """\
// Written by `cloudsmith credential-helper install sbt`.
resolvers += "cloudsmith-maven-tools" at "{repository_url}"
addSbtPlugin("io.cloudsmith" % "sbt-cloudsmith" % "{version}")
"""


class SbtInstaller(ConfigFileInstaller):
    name = "sbt"
    summary = "sbt plugin that gets credentials from the Cloudsmith CLI"
    artifact_path = "io/cloudsmith/sbt-cloudsmith_2.12_1.0"

    def path(self) -> Path:
        return Path.home() / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"

    def local_path(self) -> Path:
        # sbt loads every .sbt file in project/, so the build's own files stay as they are.
        project_dir = Path.cwd()
        if not (project_dir / "build.sbt").is_file():
            raise ProjectNotFound(
                f"No build.sbt in {project_dir}. "
                "Run the command in the root directory of an sbt project."
            )
        return project_dir / "project" / "cloudsmith.sbt"

    def render(self, version: str) -> str:
        return GLOBAL_PLUGIN.format(repository_url=REPOSITORY_URL, version=version)
