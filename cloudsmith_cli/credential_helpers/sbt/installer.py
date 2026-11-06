# Copyright 2026 Cloudsmith Ltd
"""Add the Cloudsmith sbt plugin to every sbt 1 build of the user."""

from __future__ import annotations

import re
import shutil
from functools import partial
from pathlib import Path

from .. import maven_tools
from ..maven_tools import (
    REPOSITORY_URL,
    ConfigFileInstaller,
    ProjectNotFound,
    current_dir,
)

GLOBAL_PLUGIN = """\
// Written by `cloudsmith credential-helper install sbt`.
resolvers += "cloudsmith-maven-tools" at "{repository_url}"
addSbtPlugin("io.cloudsmith" % "sbt-cloudsmith" % "{version}")
"""
_PROBE_BUILD = """\
val cloudsmithGlobalPlugins = taskKey[Unit]("Print the global plugins directory of sbt 1.")
cloudsmithGlobalPlugins := {
  val s = state.value
  if (sbtBinaryVersion.value.startsWith("1."))
    println("CLOUDSMITH_SBT_GLOBAL_PLUGINS=" +
      BuildPaths.getGlobalPluginsDirectory(s, BuildPaths.getGlobalBase(s)).getAbsolutePath)
}
"""
_GLOBAL_PLUGINS_LINE = re.compile(r"^CLOUDSMITH_SBT_GLOBAL_PLUGINS=(.+)$", re.MULTILINE)


def _reported_global_plugins(sbt: str, cwd: Path) -> Path | None:
    """Return the global plugins directory that sbt 1 prints when it runs in ``cwd``."""
    (cwd / "build.sbt").write_text(_PROBE_BUILD, encoding="utf-8")
    output = maven_tools.tool_output(
        [sbt, "-batch", "-no-colors", "cloudsmithGlobalPlugins"], cwd
    )
    match = _GLOBAL_PLUGINS_LINE.search(output)
    return Path(match.group(1)) if match else None


class SbtInstaller(ConfigFileInstaller):
    name = "sbt"
    summary = "sbt plugin that gets credentials from the Cloudsmith CLI"
    artifact_path = "io/cloudsmith/sbt-cloudsmith_2.12_1.0"

    def path(self) -> Path:
        return Path.home() / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"

    def tool_path(self) -> Path:
        """Return the plugin file in the global plugins directory that ``sbt`` reports."""
        sbt = shutil.which("sbt")
        if sbt is None:
            return self.path()
        global_plugins = maven_tools.ask_outside_projects(
            partial(_reported_global_plugins, sbt),
            "The global base of sbt is a relative path, so each build looks for the "
            "plugin in its own directory. Set an absolute path for sbt.global.base, "
            "or run `cloudsmith credential-helper install sbt --local` in each project.",
        )
        return global_plugins / "cloudsmith.sbt" if global_plugins else self.path()

    def local_path(self) -> Path:
        # sbt loads every .sbt file in project/, so the build's own files stay as they are.
        project_dir = current_dir()
        meta_dir = project_dir / "project"
        plugin_file = meta_dir / "cloudsmith.sbt"
        # sbt reads any .sbt file in the root, and a build can have only project/.
        build_files = [
            *project_dir.glob("*.sbt"),
            meta_dir / "build.properties",
            *meta_dir.glob("*.sbt"),
            *meta_dir.glob("*.scala"),
        ]
        is_project = any(path.is_file() for path in build_files)
        if not is_project:
            raise ProjectNotFound(
                f"No build.sbt in {project_dir}. "
                "Run the command in the root directory of an sbt project."
            )
        return plugin_file

    def render(self, version: str) -> str:
        return GLOBAL_PLUGIN.format(repository_url=REPOSITORY_URL, version=version)
