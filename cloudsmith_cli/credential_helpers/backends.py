# Copyright 2026 Cloudsmith Ltd
"""Backend-kind enumeration for credential helpers."""

from enum import IntEnum


class BackendKind(IntEnum):
    """Mirror of the server-side BackendKind enum (cloudsmith/package/enums.py)."""

    DEB = 0
    RPM = 1
    RUBY = 2
    PYTHON = 3
    MAVEN = 4
    BOWER = 5
    DOCKER = 6
    RAW = 7
    CHOCOLATEY = 8
    NPM = 9
    NUGET = 10
    VAGRANT = 11
    COMPOSER = 12
    ALPINE = 13
    HELM = 14
    CONAN = 15
    CARGO = 16
    LUAROCKS = 17
    CRAN = 18
    GO = 19
    DART = 20
    COCOAPODS = 21
    TERRAFORM = 22
    P2 = 23
    CONDA = 24
    HEX = 25
    SWIFT = 26
    HUGGINGFACE = 27
    GENERIC = 28
    VSX = 29
    MCP = 30
    DEFAULT = 99
