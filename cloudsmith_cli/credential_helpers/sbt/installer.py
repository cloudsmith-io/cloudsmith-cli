# Copyright 2026 Cloudsmith Ltd
"""Add the Cloudsmith sbt plugin to every sbt 1 build of the user."""

from __future__ import annotations

import re
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
_SBT_1_LINE = re.compile(r"^\[info\] welcome to sbt 1\.", re.MULTILINE)
_LOADING_GLOBAL_PLUGINS_LINE = re.compile(
    r"^\[info\] loading global plugins from (.+)$", re.MULTILINE
)


class SbtInstaller(ConfigFileInstaller):
    name = "sbt"
    summary = "sbt plugin that gets credentials from the Cloudsmith CLI"
    artifact_path = "io/cloudsmith/sbt-cloudsmith_2.12_1.0"
    tool = "sbt"
    reported = "global plugins directory"
    relative_message = (
        "The global base of sbt is a relative path, so each build looks for the "
        "plugin in its own directory. Set an absolute path for sbt.global.base, or "
        "run `cloudsmith credential-helper install sbt --local` in each project."
    )

    def path(self) -> Path:
        return Path.home() / ".sbt" / "1.0" / "plugins" / "cloudsmith.sbt"

    def reported_path(self, executable: str, cwd: Path) -> Path | None:
        """Return the plugin file in the global plugins directory that sbt 1 prints."""
        (cwd / "build.sbt").write_text(_PROBE_BUILD, encoding="utf-8")
        output = maven_tools.tool_output(
            [executable, "-batch", "-no-colors", "cloudsmithGlobalPlugins"], cwd
        )
        match = _GLOBAL_PLUGINS_LINE.search(output)
        if match is None and _SBT_1_LINE.search(output):
            # sbt names the directory before it fails to load a plugin in it.
            match = _LOADING_GLOBAL_PLUGINS_LINE.search(output)
        return Path(match.group(1)) / "cloudsmith.sbt" if match else None

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
