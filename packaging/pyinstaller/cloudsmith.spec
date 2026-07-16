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
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += ["boto3", "botocore.exceptions"]

for dist in ("cloudsmith-cli", "cloudsmith-api", "mcp", "keyring"):
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
        "cloudsmith_cli.core.tests",
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
