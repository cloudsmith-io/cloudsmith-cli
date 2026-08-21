# -*- mode: python ; coding: utf-8 -*-
# Copyright 2026 Cloudsmith Ltd
# PyInstaller onedir spec for the Cloudsmith CLI. Built natively per target.
# onedir (not onefile): onefile re-extracts the whole bundle on every
# invocation (~6s/run); onedir starts in ~0.4s. Distributed as tar.gz/zip.

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

datas, binaries, hiddenimports = [], [], []

datas += collect_data_files(
    "cloudsmith_cli",
    includes=["data/*", "templates/*"],
)
datas += collect_data_files("mcp", includes=["py.typed"])

# mcp.cli imports the optional `typer` dependency. Keep mcp.client and exclude
# only the CLI package itself and its descendants.
hiddenimports += collect_submodules(
    "mcp",
    filter=lambda name: name != "mcp.cli" and not name.startswith("mcp.cli."),
)
# Command modules load lazily via cli/commands/registry.py, so the static
# import graph from entry.py no longer reaches them. Collect the whole
# package; the Analysis excludes drop the test packages.
hiddenimports += collect_submodules("cloudsmith_cli")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("keyrings.cryptfile")
hiddenimports += collect_submodules("keyrings.alt")
hiddenimports += ["boto3", "botocore.exceptions"]

# keyring discovers backends via importlib.metadata entry points, so the
# extra backend packages need their dist metadata bundled too, not just
# their modules, or keyring won't see them as installed.
for dist in (
    "cloudsmith-cli",
    "cloudsmith-api",
    "mcp",
    "keyring",
    "keyrings.cryptfile",
    "keyrings.alt",
):
    datas += copy_metadata(dist)

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter",
        "pytest",
        "pylint",
        "black",
        "isort",
        "mcp.cli",
        "cloudsmith_cli.cli.tests",
        "cloudsmith_cli.conftest",
        "cloudsmith_cli.core.tests",
        "cloudsmith_cli.credential_helpers.pnpm.tests",
        "keyrings.cryptfile.tests",
    ],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cloudsmith",
    console=True,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="cloudsmith",
    strip=False,
    upx=False,
)
