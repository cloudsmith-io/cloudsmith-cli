# PEX Platform Files

Platform JSON files for building universal Python zipapps that work across operating systems, architectures, and Python versions.

## Supported Platforms

- Linux x86_64 (glibc) - Debian, Ubuntu, RHEL, CentOS
- Linux ARM64 (glibc) - ARM-based Linux servers
- Linux x86_64 (musl) - Alpine Linux
- Linux ARM64 (musl) - Alpine Linux ARM
- macOS ARM64 - Apple Silicon
- Windows x86_64 - Windows 10/11

**Python versions:** 3.10, 3.11, 3.12, 3.13, 3.14

## When to Regenerate

Regenerate platform files when:
- Adding support for new Python versions
- Dependencies change (especially packages with C extensions)
- Build failures on specific platforms

**Note:** The script skips existing valid files. When dependencies change, delete the existing platform files first:
```bash
rm .github/.platforms/*.json
.github/.platforms/generate_platforms.py
```

## How to Regenerate

**Requirements:**
- Docker
- Internet connection
- Python 3.10-3.14 (for macOS platform files only)

**Run:**
```bash
.github/.platforms/generate_platforms.py
```

The script skips existing files and retries failures automatically.

**Force regeneration:**
```bash
rm .github/.platforms/*.json
.github/.platforms/generate_platforms.py
```
