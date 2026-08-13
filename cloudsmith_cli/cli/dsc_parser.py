"""Parse Debian ``.dsc`` control files for ``push deb --dsc-file``."""

import os
from email.parser import Parser

import click

_CLEAR_SIGNED_MESSAGE = "-----BEGIN PGP SIGNED MESSAGE-----"
_SIGNATURE = "-----BEGIN PGP SIGNATURE-----"
_DETACHED_SIGNATURE_SUFFIX = ".asc"
_FILE_LIST_FIELDS = ("Checksums-Sha256", "Files")
_QUILT_FORMATS = {"2.0", "3.0 (quilt)"}
_SINGLE_TARBALL_FORMATS = {"3.0 (native)", "3.0 (git)", "3.0 (bzr)"}


def _usage_error(dsc_path, message):
    return click.UsageError(f"--dsc-file {dsc_path!r} {message}")


def _unwrap_clearsigned_control(text, dsc_path):
    """Return deb822 control text from an optional OpenPGP cleartext signature."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != _CLEAR_SIGNED_MESSAGE:
        return text

    index = 1
    while index < len(lines) and lines[index].rstrip("\r\n"):
        index += 1
    if index == len(lines):
        raise _usage_error(dsc_path, "has a malformed OpenPGP cleartext signature.")

    cleartext = []
    for line in lines[index + 1 :]:
        if line.rstrip("\r\n") == _SIGNATURE:
            return "".join(cleartext)
        # RFC 9580 cleartext signatures dash-escape lines beginning with "-".
        cleartext.append(line.removeprefix("- "))

    raise _usage_error(dsc_path, "has a malformed OpenPGP cleartext signature.")


def _read_control_message(dsc_path):
    """Parse ``dsc_path`` as a plain or OpenPGP-clearsigned deb822 stanza."""
    try:
        with open(dsc_path, encoding="utf-8", errors="replace") as dsc_fh:
            text = dsc_fh.read()
    except OSError as exc:
        raise _usage_error(dsc_path, f"could not be read: {exc}") from exc

    return Parser().parsestr(_unwrap_clearsigned_control(text, dsc_path))


def _parse_file_list(field_name, field_value, dsc_path):
    filenames = []
    for line in field_value.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            raise _usage_error(
                dsc_path,
                f"has a malformed {field_name!r} entry {line.strip()!r}; "
                "expected '<checksum> <size> <filename>'.",
            )
        filenames.append(parts[2])
    return filenames


def _extract_filenames(message, dsc_path):
    """Return an agreed filename list, preferring the strong SHA-256 field."""
    file_lists = {}
    for field_name in _FILE_LIST_FIELDS:
        field_value = message.get(field_name)
        if field_value:
            filenames = _parse_file_list(field_name, field_value, dsc_path)
            if filenames:
                file_lists[field_name] = filenames

    if not file_lists:
        raise _usage_error(
            dsc_path,
            "has no non-empty 'Checksums-Sha256:' or 'Files:' field to parse.",
        )

    for filenames in file_lists.values():
        if len(filenames) != len(set(filenames)):
            raise _usage_error(dsc_path, "lists the same source-package member twice.")

    selected_name = next(iter(file_lists))
    selected = file_lists[selected_name]
    for field_name, filenames in file_lists.items():
        if set(filenames) != set(selected):
            raise _usage_error(
                dsc_path,
                f"has conflicting filenames in {selected_name!r} and {field_name!r}.",
            )

    return selected


def _required_field(message, field_name, dsc_path):
    value = message.get(field_name)
    if not value or not value.strip():
        raise _usage_error(dsc_path, f"has no {field_name!r} field.")
    return value.strip()


def _validate_member_names(filenames, dsc_path):
    for filename in filenames:
        if os.path.isabs(filename) or os.path.basename(filename) != filename:
            raise _usage_error(
                dsc_path,
                f"references invalid member filename {filename!r}; source-package "
                "members must be filenames next to the .dsc, not paths.",
            )


def _is_tar_archive(filename, stem):
    prefix = f"{stem}.tar."
    return filename.startswith(prefix) and len(filename) > len(prefix)


def _classify_members(message, filenames, dsc_path):
    """Map source-package members to the two fields accepted by the SDK."""
    source = _required_field(message, "Source", dsc_path)
    version = _required_field(message, "Version", dsc_path).split(":", 1)[-1]
    source_format = _required_field(message, "Format", dsc_path)
    upstream_version = version.rsplit("-", 1)[0]

    signature_files = [
        filename
        for filename in filenames
        if filename.endswith(_DETACHED_SIGNATURE_SUFFIX)
    ]
    if signature_files:
        raise _usage_error(
            dsc_path,
            "references detached upstream signature file(s) ({files}). Cloudsmith "
            "does not support detached upstream signatures for deb uploads.".format(
                files=", ".join(signature_files)
            ),
        )

    sources = []
    changes = []
    component_files = []
    legacy_non_native = False

    if source_format in _QUILT_FORMATS:
        orig_stem = f"{source}_{upstream_version}.orig"
        component_prefix = f"{orig_stem}-"
        debian_stem = f"{source}_{version}.debian"
        sources = [f for f in filenames if _is_tar_archive(f, orig_stem)]
        changes = [f for f in filenames if _is_tar_archive(f, debian_stem)]
        component_files = [
            f
            for f in filenames
            if f.startswith(component_prefix) and ".tar." in f[len(component_prefix) :]
        ]
    elif source_format == "1.0":
        orig_stem = f"{source}_{upstream_version}.orig"
        diff_name = f"{source}_{version}.diff.gz"
        native_stem = f"{source}_{version}"
        orig_files = [f for f in filenames if _is_tar_archive(f, orig_stem)]
        diff_files = [f for f in filenames if f == diff_name]
        native_files = [f for f in filenames if _is_tar_archive(f, native_stem)]
        if orig_files or diff_files:
            legacy_non_native = True
            sources = orig_files
            changes = diff_files
        else:
            sources = native_files
    elif source_format in _SINGLE_TARBALL_FORMATS:
        sources = [f for f in filenames if _is_tar_archive(f, f"{source}_{version}")]
    else:
        raise _usage_error(
            dsc_path, f"uses unsupported Debian source format {source_format!r}."
        )

    if component_files:
        raise _usage_error(
            dsc_path,
            "references a multi-component source package ({files}). Cloudsmith "
            "does not support multi-component Debian source packages for deb "
            "uploads.".format(files=", ".join(component_files)),
        )

    classified = set(sources + changes + signature_files + component_files)
    unexpected = [f for f in filenames if f not in classified]
    if unexpected:
        raise _usage_error(
            dsc_path,
            "contains unsupported or incorrectly named source-package member(s) "
            f"({', '.join(unexpected)}) for format {source_format!r}.",
        )
    if len(sources) != 1:
        raise _usage_error(
            dsc_path,
            f"must reference exactly one main source archive for format "
            f"{source_format!r}; found {len(sources)}.",
        )
    if source_format in _QUILT_FORMATS and len(changes) != 1:
        raise _usage_error(
            dsc_path,
            f"must reference exactly one Debian packaging archive for format "
            f"{source_format!r}; found {len(changes)}.",
        )
    if legacy_non_native and len(changes) != 1:
        raise _usage_error(
            dsc_path,
            "must reference exactly one Debian packaging diff for non-native "
            f"format '1.0'; found {len(changes)}.",
        )

    return sources[0], changes[0] if changes else None


def _resolve_member(base_dir, filename, dsc_path):
    candidate = os.path.join(base_dir, filename)
    resolved = os.path.realpath(candidate)
    if os.path.dirname(resolved) != base_dir or not os.path.isfile(resolved):
        raise _usage_error(
            dsc_path,
            f"references {filename!r}, but it is not a regular file directly "
            "next to the .dsc.",
        )
    return resolved


def resolve_dsc_files(dsc_path):
    """Return ``(sources_file, changes_file)`` derived from a Debian ``.dsc``."""
    message = _read_control_message(dsc_path)
    filenames = _extract_filenames(message, dsc_path)
    _validate_member_names(filenames, dsc_path)
    source_filename, changes_filename = _classify_members(message, filenames, dsc_path)

    base_dir = os.path.realpath(os.path.dirname(os.path.abspath(dsc_path)))
    sources_file = _resolve_member(base_dir, source_filename, dsc_path)
    changes_file = (
        _resolve_member(base_dir, changes_filename, dsc_path)
        if changes_filename
        else None
    )
    return sources_file, changes_file
