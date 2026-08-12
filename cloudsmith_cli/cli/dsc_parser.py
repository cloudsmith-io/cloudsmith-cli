"""CLI - Parse Debian ``.dsc`` control files for ``push deb --dsc-file``.

A ``.dsc`` (Debian source control) file is an RFC822-style control file that
lists the other files making up a Debian source package (the orig tarball,
the debian packaging tarball/diff, and optionally a detached signature or
extra "component" tarballs) in its ``Files:`` and/or ``Checksums-Sha256:``
stanza. This module extracts those filenames so ``cloudsmith push deb`` can
derive ``--sources-file``/``--changes-file`` automatically instead of
requiring both to be passed by hand (see GitHub issue #56).

Only a single-tarball, non-signed source package is supported, matching what
Cloudsmith's ``deb`` package-upload format actually accepts:

- Multi-component source packages (extra ``*.orig-component.tar.*`` files)
  and detached upstream signatures (``*.asc``) referenced by the ``.dsc``
  are rejected with a clear error rather than silently dropped, since the
  Cloudsmith backend has nowhere to put them.
"""

import os
from email.parser import Parser

import click

#: Marker identifying a multi-component source tarball reference
#: (e.g. ``foo_1.0.orig-libbar.tar.gz``). Cloudsmith's ``deb`` upload format
#: only accepts a single source tarball, so a ``.dsc`` referencing one of
#: these can't be represented and must be rejected rather than guessed at.
_MULTI_COMPONENT_MARKER = ".orig-"

#: Suffix identifying a detached signature file (e.g. a ``.dsc.asc`` or an
#: ``.orig.tar.gz.asc``). Cloudsmith's ``deb`` upload format has no field for
#: a detached signature, so these must be rejected rather than silently
#: dropped.
_DETACHED_SIGNATURE_SUFFIX = ".asc"

_CHANGES_SUFFIX = ".changes"
_DSC_SUFFIX = ".dsc"

#: The stanza names that carry the file listing in a ``.dsc``, in the order
#: they're checked. ``Files:`` (MD5) is present in every ``.dsc``;
#: ``Checksums-Sha256:`` is the modern equivalent. Either is sufficient.
_FILE_LIST_FIELDS = ("Files", "Checksums-Sha256")


def _read_control_message(dsc_path):
    """Parse ``dsc_path`` as an RFC822-style control file.

    Uses the stdlib ``email.parser`` rather than a new dependency (e.g.
    ``python-debian``) since a ``.dsc``'s single stanza is plain RFC822
    headers followed by (in modern ``.dsc`` files) an inline PGP signature,
    which we don't need to verify or even skip explicitly -- the signature
    lines simply aren't valid headers and are ignored by the permissive
    parser.
    """
    try:
        with open(dsc_path, encoding="utf-8", errors="replace") as dsc_fh:
            return Parser().parse(dsc_fh)
    except OSError as exc:
        raise click.UsageError(
            f"Could not read --dsc-file {dsc_path!r}: {exc}"
        ) from exc


def _extract_filenames(message, dsc_path):
    """Return the filenames listed in a ``.dsc``'s file-listing stanza.

    Each non-blank line of ``Files:``/``Checksums-Sha256:`` looks like
    ``<checksum> <size> [<section> <priority>] <filename>``; only the
    trailing filename token is needed.
    """
    for field_name in _FILE_LIST_FIELDS:
        field_value = message.get(field_name)
        if not field_value:
            continue

        filenames = [
            line.split()[-1] for line in field_value.splitlines() if line.split()
        ]
        if filenames:
            return filenames

    raise click.UsageError(
        f"--dsc-file {dsc_path!r} has no (non-empty) 'Files:' or "
        "'Checksums-Sha256:' stanza to parse."
    )


def resolve_dsc_files(dsc_path):
    """Resolve the source tarball and (optional) changes file for a ``.dsc``.

    Returns a ``(sources_file, changes_file)`` tuple of paths resolved
    relative to the directory containing ``dsc_path``. ``changes_file`` is
    ``None`` when the ``.dsc`` doesn't reference one -- a ``.dsc`` describes
    the source package itself, and pairing it with a ``.changes`` file is
    optional (e.g. when the package was never built/uploaded with
    ``dpkg-genchanges``).

    Raises ``click.UsageError`` when:

    - the ``.dsc`` references a detached signature (``*.asc``) or a
      multi-component source tarball (``*.orig-<component>.tar.*``) --
      Cloudsmith's ``deb`` upload format doesn't support either, so this
      fails loudly instead of silently dropping the reference or uploading
      the wrong file.
    - the remaining files don't resolve to exactly one source tarball, or
      more than one ``.changes`` file.
    - a referenced file doesn't exist on disk next to the ``.dsc``.
    """
    message = _read_control_message(dsc_path)
    filenames = _extract_filenames(message, dsc_path)

    signature_files = [f for f in filenames if f.endswith(_DETACHED_SIGNATURE_SUFFIX)]
    if signature_files:
        raise click.UsageError(
            "--dsc-file {dsc!r} references a detached signature file ({files}). "
            "Cloudsmith does not support detached upstream signatures for deb "
            "uploads.".format(dsc=dsc_path, files=", ".join(signature_files))
        )

    multi_component_files = [f for f in filenames if _MULTI_COMPONENT_MARKER in f]
    if multi_component_files:
        raise click.UsageError(
            "--dsc-file {dsc!r} references a multi-component source package "
            "({files}). Cloudsmith does not support multi-component Debian "
            "source packages for deb uploads.".format(
                dsc=dsc_path, files=", ".join(multi_component_files)
            )
        )

    changes_files = [f for f in filenames if f.endswith(_CHANGES_SUFFIX)]
    if len(changes_files) > 1:
        raise click.UsageError(
            "--dsc-file {dsc!r} references more than one .changes file "
            "({files}); expected at most one.".format(
                dsc=dsc_path, files=", ".join(changes_files)
            )
        )

    source_files = [
        f for f in filenames if f not in changes_files and not f.endswith(_DSC_SUFFIX)
    ]
    if not source_files:
        raise click.UsageError(
            f"--dsc-file {dsc_path!r} does not reference a source tarball."
        )
    if len(source_files) > 1:
        raise click.UsageError(
            "--dsc-file {dsc!r} references more than one source tarball "
            "({files}); expected exactly one non-signature, "
            "non-multi-component file.".format(
                dsc=dsc_path, files=", ".join(source_files)
            )
        )

    base_dir = os.path.dirname(os.path.abspath(dsc_path))

    def _resolve(filename):
        resolved = os.path.join(base_dir, filename)
        if not os.path.isfile(resolved):
            raise click.UsageError(
                f"--dsc-file {dsc_path!r} references {filename!r}, but it "
                f"was not found next to the .dsc (expected at {resolved!r})."
            )
        return resolved

    sources_file = _resolve(source_files[0])
    changes_file = _resolve(changes_files[0]) if changes_files else None
    return sources_file, changes_file
