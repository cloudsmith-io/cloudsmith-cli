# Copyright 2026 Cloudsmith Ltd
"""Tests for cloudsmith_cli.core.cache_utils."""

from __future__ import annotations

import json
import os
import stat

from cloudsmith_cli.core.cache_utils import atomic_write_json, merge_json_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _perms(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


# ---------------------------------------------------------------------------
# atomic_write_json — basic round-trip and permissions
# ---------------------------------------------------------------------------


class TestAtomicWriteJson:
    def test_round_trip(self, tmp_path):
        dest = str(tmp_path / "data.json")
        data = {"key": "value", "nested": {"a": 1}}
        atomic_write_json(dest, data)
        assert _read_json(dest) == data

    def test_default_permissions(self, tmp_path):
        dest = str(tmp_path / "data.json")
        atomic_write_json(dest, {"x": 1})
        assert _perms(dest) == 0o600

    def test_custom_permissions(self, tmp_path):
        dest = str(tmp_path / "data.json")
        atomic_write_json(dest, {"x": 1}, mode=0o644)
        assert _perms(dest) == 0o644

    def test_overwrites_existing(self, tmp_path):
        dest = str(tmp_path / "data.json")
        atomic_write_json(dest, {"v": 1})
        atomic_write_json(dest, {"v": 2})
        assert _read_json(dest) == {"v": 2}


# ---------------------------------------------------------------------------
# merge_json_file
# ---------------------------------------------------------------------------


def _add_cred_helper(host: str):
    """Return a mutate function that adds a credHelpers entry."""

    def mutate(data: dict) -> None:
        data.setdefault("credHelpers", {})[host] = "cloudsmith"

    return mutate


class TestMergeJsonFileForeignKeyPreservation:
    """Foreign-key preservation: only touched keys change."""

    def test_existing_keys_preserved(self, tmp_path):
        path = str(tmp_path / "config.json")
        initial = {
            "auths": {"registry.example.com": {"auth": "dXNlcjpwYXNz"}},
            "credHelpers": {"x.example.com": "y"},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(initial, f)

        changed = merge_json_file(
            path,
            _add_cred_helper("docker.cloudsmith.io"),
        )

        assert changed is True
        result = _read_json(path)
        assert result["auths"] == initial["auths"]
        assert result["credHelpers"]["x.example.com"] == "y"
        assert result["credHelpers"]["docker.cloudsmith.io"] == "cloudsmith"

    def test_key_order_not_sorted(self, tmp_path):
        """Keys must stay in insertion order, not sorted."""
        path = str(tmp_path / "config.json")
        # Write with z-first order via json module (which preserves insertion order)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"zzz": 1, "aaa": 2}, f)

        def noop(data: dict) -> None:
            data["new_key"] = 3

        merge_json_file(path, noop)
        text = _read_text(path)
        assert text.index('"zzz"') < text.index('"aaa"'), "Key order must be preserved"


class TestMergeJsonFileCreatesMissingFile:
    """Creates a new file starting from {} when the file is absent."""

    def test_creates_file_when_missing(self, tmp_path):
        path = str(tmp_path / "subdir" / "config.json")
        changed = merge_json_file(path, _add_cred_helper("docker.cloudsmith.io"))
        assert changed is True
        assert os.path.exists(path)
        result = _read_json(path)
        assert result == {"credHelpers": {"docker.cloudsmith.io": "cloudsmith"}}

    def test_creates_parent_directory(self, tmp_path):
        path = str(tmp_path / "missing_dir" / "config.json")
        assert not os.path.exists(os.path.dirname(path))
        merge_json_file(path, _add_cred_helper("x"))
        assert os.path.isdir(os.path.dirname(path))

    def test_parent_dir_permissions(self, tmp_path):
        path = str(tmp_path / "newdir" / "config.json")
        merge_json_file(path, _add_cred_helper("x"))
        parent_perms = _perms(os.path.dirname(path))
        assert parent_perms == 0o700

    def test_file_permissions_after_create(self, tmp_path):
        path = str(tmp_path / "newdir" / "config.json")
        merge_json_file(path, _add_cred_helper("x"))
        assert _perms(path) == 0o600


class TestMergeJsonFileBackup:
    """Backup behaviour: .bak is created with prior content when writing."""

    def test_backup_created_on_change(self, tmp_path):
        path = str(tmp_path / "config.json")
        initial = {"auths": {}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(initial, f)

        merge_json_file(path, _add_cred_helper("docker.cloudsmith.io"))

        bak_path = path + ".bak"
        assert os.path.exists(bak_path), ".bak file should exist after a change"
        assert _read_json(bak_path) == initial

    def test_no_backup_when_file_missing(self, tmp_path):
        path = str(tmp_path / "config.json")
        merge_json_file(path, _add_cred_helper("x"))
        assert not os.path.exists(path + ".bak")

    def test_no_backup_when_no_change(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"credHelpers": {"x": "cloudsmith"}}, indent=2) + "\n")

        def noop_already_set(data: dict) -> None:
            data.setdefault("credHelpers", {})["x"] = "cloudsmith"

        changed = merge_json_file(path, noop_already_set)
        assert changed is False
        assert not os.path.exists(path + ".bak")

    def test_backup_is_mode_0o600_regardless_of_source_perms(self, tmp_path):
        """The .bak must always be written 0o600 even when the source is 0o644."""
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"auths": {}}, f)
        os.chmod(path, 0o644)

        merge_json_file(path, _add_cred_helper("docker.cloudsmith.io"))

        bak_path = path + ".bak"
        assert os.path.exists(bak_path), ".bak must be created"
        assert (
            _perms(bak_path) == 0o600
        ), f".bak perms should be 0o600, got {oct(_perms(bak_path))}"


class TestMergeJsonFileIdempotent:
    """Running the same merge twice: second call returns False, no new .bak."""

    def test_idempotent_returns_false_second_call(self, tmp_path):
        path = str(tmp_path / "config.json")
        mutate = _add_cred_helper("docker.cloudsmith.io")

        first = merge_json_file(path, mutate)
        assert first is True

        second = merge_json_file(path, mutate)
        assert second is False

    def test_idempotent_no_overwrite_bak(self, tmp_path):
        path = str(tmp_path / "config.json")
        initial = {"auths": {}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(initial, f)

        mutate = _add_cred_helper("docker.cloudsmith.io")
        merge_json_file(path, mutate)  # first: changes file, writes .bak

        bak_path = path + ".bak"
        bak_mtime_after_first = os.path.getmtime(bak_path)

        merge_json_file(path, mutate)  # second: no change

        bak_mtime_after_second = os.path.getmtime(bak_path)
        assert (
            bak_mtime_after_first == bak_mtime_after_second
        ), ".bak must not be refreshed"


class TestMergeJsonFileDryRun:
    """dry_run=True: correct return value, no file written."""

    def test_dry_run_returns_true_when_would_change(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)

        result = merge_json_file(path, _add_cred_helper("x"), dry_run=True)
        assert result is True

    def test_dry_run_file_unchanged(self, tmp_path):
        path = str(tmp_path / "config.json")
        original_text = json.dumps({}) + "\n"
        # Write exactly the content we'll compare against
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"existing": True}, indent=2) + "\n")
        original_text = _read_text(path)

        merge_json_file(path, _add_cred_helper("x"), dry_run=True)

        assert _read_text(path) == original_text, "dry_run must not modify the file"

    def test_dry_run_no_bak_created(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"existing": True}, f)

        merge_json_file(path, _add_cred_helper("x"), dry_run=True)
        assert not os.path.exists(path + ".bak")

    def test_dry_run_returns_false_when_no_change(self, tmp_path):
        path = str(tmp_path / "config.json")
        # Pre-populate so mutate produces no change
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"credHelpers": {"x": "cloudsmith"}}, indent=2) + "\n")

        def already_set(data: dict) -> None:
            data.setdefault("credHelpers", {})["x"] = "cloudsmith"

        result = merge_json_file(path, already_set, dry_run=True)
        assert result is False

    def test_dry_run_missing_file_no_creation(self, tmp_path):
        path = str(tmp_path / "ghost" / "config.json")
        result = merge_json_file(path, _add_cred_helper("x"), dry_run=True)
        assert result is True
        assert not os.path.exists(path)
        assert not os.path.exists(os.path.dirname(path))


class TestMergeJsonFileMalformedInput:
    """Malformed file → treated as {}."""

    def test_malformed_json_treated_as_empty(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json")

        changed = merge_json_file(path, _add_cred_helper("docker.cloudsmith.io"))
        assert changed is True
        result = _read_json(path)
        assert result == {"credHelpers": {"docker.cloudsmith.io": "cloudsmith"}}

    def test_empty_file_treated_as_empty_dict(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8"):
            pass  # touch / create empty file

        merge_json_file(path, _add_cred_helper("x"))
        result = _read_json(path)
        assert "credHelpers" in result

    def test_json_array_treated_as_empty_dict(self, tmp_path):
        path = str(tmp_path / "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)

        merge_json_file(path, _add_cred_helper("x"))
        result = _read_json(path)
        assert isinstance(result, dict)
        assert "credHelpers" in result


class TestMergeJsonFileStableSerialization:
    """On-disk form is json.dumps(data, indent=2, ensure_ascii=False) + newline."""

    def test_output_format(self, tmp_path):
        path = str(tmp_path / "config.json")
        merge_json_file(path, _add_cred_helper("docker.cloudsmith.io"))
        text = _read_text(path)
        expected = json.dumps(
            {"credHelpers": {"docker.cloudsmith.io": "cloudsmith"}},
            indent=2,
            ensure_ascii=False,
        )
        assert text == expected + "\n"

    def test_trailing_newline(self, tmp_path):
        path = str(tmp_path / "config.json")
        merge_json_file(path, _add_cred_helper("x"))
        text = _read_text(path)
        assert text.endswith("\n")

    def test_non_ascii_host_raw_utf8_not_escaped(self, tmp_path):
        """Non-ASCII chars must be written as raw UTF-8, not \\uXXXX escapes."""
        path = str(tmp_path / "config.json")
        unicode_host = "café.docker.example.com"
        mutate = _add_cred_helper(unicode_host)

        # First call: file is created (content changes → True)
        first = merge_json_file(path, mutate)
        assert first is True

        # The written file must contain the raw Unicode character
        with open(path, "rb") as fh:
            raw_bytes = fh.read()
        assert "café".encode() in raw_bytes, "expected raw UTF-8, not \\uXXXX"
        assert (
            b"\\u" not in raw_bytes
        ), "must not use JSON unicode escapes for non-ASCII"

        # Second call: identical mutate → no change (idempotent)
        bak_path = path + ".bak"
        bak_mtime_before = (
            os.path.getmtime(bak_path) if os.path.exists(bak_path) else None
        )

        second = merge_json_file(path, mutate)
        assert second is False

        # .bak must not have been touched on the no-op call
        if bak_mtime_before is not None:
            assert (
                os.path.getmtime(bak_path) == bak_mtime_before
            ), ".bak must not refresh"
        else:
            assert not os.path.exists(bak_path), ".bak must not be created on no-op"


class TestMergeJsonFileReturnValue:
    """Return True on change, False on no-change."""

    def test_returns_true_on_actual_write(self, tmp_path):
        path = str(tmp_path / "config.json")
        result = merge_json_file(path, _add_cred_helper("x"))
        assert result is True

    def test_returns_false_on_no_change(self, tmp_path):
        path = str(tmp_path / "config.json")
        mutate = _add_cred_helper("x")
        merge_json_file(path, mutate)
        result = merge_json_file(path, mutate)
        assert result is False
