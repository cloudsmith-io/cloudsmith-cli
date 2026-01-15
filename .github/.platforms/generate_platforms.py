#!/usr/bin/env python3
"""Generate PEX platform files for multi-platform Python zipapp builds."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

# Configuration
PYTHON_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# Stable ABI (abi3) wheels built for older Python work on newer versions.
# Most packages build abi3 wheels against 3.7-3.10 for maximum compatibility.
ABI3_PREFIXES = ("cp310-abi3-", "cp39-abi3-", "cp38-abi3-", "cp37-abi3-")

T = TypeVar("T")


@dataclass(frozen=True)
class Platform:
    """Platform configuration for generating PEX platform files."""

    name: str
    docker_platform: str
    docker_image: str
    use_alpine_shell: bool = False

    @property
    def shell(self) -> list[str]:
        return ["sh", "-c"] if self.use_alpine_shell else ["bash", "-c"]


def get_platforms(py_version: str) -> list[Platform]:
    """Return platform configurations for a Python version."""
    return [
        Platform("linux-x86_64", "linux/amd64", f"python:{py_version}-slim"),
        Platform("linux-aarch64", "linux/arm64", f"python:{py_version}-slim"),
        Platform(
            "linux-x86_64-musl",
            "linux/amd64",
            f"python:{py_version}-alpine",
            use_alpine_shell=True,
        ),
        Platform(
            "linux-aarch64-musl",
            "linux/arm64",
            f"python:{py_version}-alpine",
            use_alpine_shell=True,
        ),
    ]


def retry(
    max_attempts: int = MAX_RETRIES,
) -> Callable[[Callable[[], T]], Callable[[], T]]:
    """Decorator for retrying functions with exponential backoff."""

    def decorator(func: Callable[[], T]) -> Callable[[], T]:
        def wrapper() -> T:
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func()
                except subprocess.CalledProcessError as e:
                    last_error = e
                    if attempt < max_attempts:
                        delay = RETRY_DELAY_SECONDS * attempt
                        print(
                            f"    ⚠ Attempt {attempt} failed, retrying in {delay}s...",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
            if last_error is not None:
                raise last_error
            raise RuntimeError(
                f"Retry failed without capturing a CalledProcessError. "
                f"max_attempts={max_attempts!r}"
            )

        return wrapper

    return decorator


def is_valid(file_path: Path) -> bool:
    """Check if platform file exists with required JSON structure."""
    if not file_path.exists():
        return False
    try:
        data = json.loads(file_path.read_text())
        return "marker_environment" in data and "compatible_tags" in data
    except (json.JSONDecodeError, OSError):
        return False


def filter_tags(tags: list[str], py_minor: str) -> list[str]:
    """Keep only necessary wheel tags for the target Python version."""
    return [
        tag
        for tag in tags
        if tag.startswith((f"cp{py_minor}-", f"py{py_minor}-", "py3-none-"))
        or tag.startswith(ABI3_PREFIXES)
    ]


def write_platform_json(path: Path, data: dict, py_minor: str) -> None:
    """Write platform JSON with filtered tags and consistent key order."""
    if "compatible_tags" in data:
        data["compatible_tags"] = filter_tags(data["compatible_tags"], py_minor)

    output = {
        k: data[k] for k in ("marker_environment", "compatible_tags") if k in data
    }
    path.write_text(json.dumps(output, indent=2) + "\n")


def run_docker(platform: Platform, command: str) -> str:
    """Execute command in Docker container and return stdout."""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform.docker_platform,
            platform.docker_image,
            *platform.shell,
            command,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def generate_docker(
    platform: Platform, py_version: str, py_minor: str, output_dir: Path
) -> bool:
    """Generate platform file using Docker."""
    output_file = output_dir / f"{platform.name}-py{py_minor}.json"
    print(f"  - {platform.name}-py{py_minor}.json")

    if is_valid(output_file):
        print("    ✓ Already exists")
        return True

    try:

        @retry()
        def fetch() -> str:
            return run_docker(
                platform,
                "pip install -q pex && pex3 interpreter inspect --markers --tags --indent 4",
            )

        output_file.write_text(fetch())
        write_platform_json(output_file, json.loads(output_file.read_text()), py_minor)
        print("    ✓ Generated")
        return True
    except subprocess.CalledProcessError as e:
        output_file.unlink(missing_ok=True)
        print(f"    ✗ Failed: {e.stderr.strip() if e.stderr else e}", file=sys.stderr)
        return False


def generate_macos(py_version: str, py_minor: str, output_dir: Path) -> bool:
    """Generate macOS platform file using local Python."""
    output_file = output_dir / f"macos-arm64-py{py_minor}.json"
    print(f"  - macos-arm64-py{py_minor}.json")

    if is_valid(output_file):
        print("    ✓ Already exists")
        return True

    python_exe = shutil.which(f"python{py_version}")
    if not python_exe:
        print(f"    ⚠ python{py_version} not available")
        return False

    with tempfile.TemporaryDirectory() as venv_dir:
        venv = Path(venv_dir)
        try:
            subprocess.run(
                [python_exe, "-m", "venv", str(venv)], check=True, capture_output=True
            )
            subprocess.run(
                [str(venv / "bin/pip"), "install", "-q", "pex"],
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [
                    str(venv / "bin/pex3"),
                    "interpreter",
                    "inspect",
                    "--markers",
                    "--tags",
                    "--indent",
                    "4",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            output_file.write_text(result.stdout)
            write_platform_json(
                output_file, json.loads(output_file.read_text()), py_minor
            )
            print("    ✓ Generated")
            return True
        except subprocess.CalledProcessError as e:
            output_file.unlink(missing_ok=True)
            print(
                f"    ✗ Failed: {e.stderr.strip() if e.stderr else e}", file=sys.stderr
            )
            return False


def generate_windows(py_version: str, py_minor: str, output_dir: Path) -> bool:
    """Generate Windows platform file from template."""
    output_file = output_dir / f"windows-x86_64-py{py_minor}.json"
    print(f"  - windows-x86_64-py{py_minor}.json")

    if is_valid(output_file):
        print("    ✓ Already exists")
        return True

    data = {
        "marker_environment": {
            "implementation_name": "cpython",
            "implementation_version": f"{py_version}.0",
            "os_name": "nt",
            "platform_machine": "AMD64",
            "platform_python_implementation": "CPython",
            "platform_release": "",
            "platform_system": "Windows",
            "platform_version": "",
            "python_full_version": f"{py_version}.0",
            "python_version": py_version,
            "sys_platform": "win32",
        },
        "compatible_tags": [
            f"cp{py_minor}-cp{py_minor}-win_amd64",
            f"cp{py_minor}-abi3-win_amd64",
            f"cp{py_minor}-none-win_amd64",
            "cp310-abi3-win_amd64",
            "cp39-abi3-win_amd64",
            "cp38-abi3-win_amd64",
            "cp37-abi3-win_amd64",
            f"py{py_minor}-none-win_amd64",
            "py3-none-win_amd64",
            f"cp{py_minor}-none-any",
            f"py{py_minor}-none-any",
            "py3-none-any",
        ],
    }
    output_file.write_text(json.dumps(data, indent=2) + "\n")
    print("    ✓ Generated")
    return True


def main() -> int:
    """Generate platform files for all Python versions."""
    output_dir = Path(__file__).parent

    print("PEX Platform Generator")
    print("=" * 22)
    print(f"Python versions: {', '.join(PYTHON_VERSIONS)}\n")

    total, failed = 0, 0

    for py_version in PYTHON_VERSIONS:
        py_minor = py_version.replace(".", "")
        print(f"Python {py_version}:")

        for platform in get_platforms(py_version):
            total += 1
            if not generate_docker(platform, py_version, py_minor, output_dir):
                failed += 1

        total += 1
        if not generate_macos(py_version, py_minor, output_dir):
            failed += 1

        total += 1
        if not generate_windows(py_version, py_minor, output_dir):
            failed += 1

        print()

    print(f"Summary\n{'=' * 7}")
    print(f"Total: {total} | Failed: {failed}")
    print(
        "✓ All platform files ready"
        if failed == 0
        else "⚠ Some files failed (re-run to retry)"
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
