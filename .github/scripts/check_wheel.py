# Copyright 2026 Cloudsmith Ltd
"""Fail if the built wheel contains packaging or test files."""
import glob
import zipfile

wheel = glob.glob("dist/*.whl")
if len(wheel) != 1:
    raise SystemExit(f"expected one wheel, found: {wheel}")
with zipfile.ZipFile(wheel[0]) as archive:
    names = archive.namelist()
forbidden = [
    name
    for name in names
    if name.startswith("packaging/") or "/tests/" in name or name.startswith("tests/")
]
if forbidden:
    raise SystemExit(f"wheel contains non-runtime files: {forbidden}")
