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

_excludes = [
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
]

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=_excludes,
)

# Second executable: terraform-credentials-cloudsmith. Terraform (notably on
# Windows) only runs a real .exe named this way and ignores .cmd shims, so it
# ships as its own binary that forwards to `credential-helper terraform`.
tf = Analysis(
    ["terraform_entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=_excludes,
)

# MERGE dedupes the shared dependency tree so the two entry scripts don't each
# carry a full copy of the collected binaries/datas in the onedir bundle.
MERGE((a, "cloudsmith", "cloudsmith"), (tf, "terraform_entry", "terraform_entry"))

pyz = PYZ(a.pure)
tf_pyz = PYZ(tf.pure)

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

tf_exe = EXE(
    tf_pyz,
    tf.scripts,
    [],
    exclude_binaries=True,
    name="terraform-credentials-cloudsmith",
    console=True,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    tf_exe,
    tf.binaries,
    tf.datas,
    name="cloudsmith",
    strip=False,
    upx=False,
)
