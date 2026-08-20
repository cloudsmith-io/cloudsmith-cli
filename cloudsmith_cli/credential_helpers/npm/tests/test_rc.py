# Copyright 2026 Cloudsmith Ltd
"""Tests for NPMRC (NPM configuration file) management."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ..rc import NPMRC, AuthKeyConflictError


class TestURLEntry:
    """Tests for NPMRC.URLEntry class."""

    def test_urlentry_from_values_with_value(self):
        """Create a URLEntry with a value from factory method."""
        entry = NPMRC.URLEntry.from_values(
            "registry.example.com", "tokenHelper", "my-helper"
        )
        assert str(entry) == "//registry.example.com/:tokenHelper=my-helper"
        assert entry._domain == "registry.example.com"
        assert entry._key == "tokenHelper"
        assert entry._value == "my-helper"

    def test_urlentry_from_values_without_value(self):
        """Create a URLEntry without a value from factory method."""
        entry = NPMRC.URLEntry.from_values("registry.example.com", "tokenHelper", None)
        # The from_values method sets _value to None, but __new__ creates the string
        # with an empty value, which then gets parsed back during __init__
        assert entry._domain == "registry.example.com"
        assert entry._key == "tokenHelper"
        assert entry._value is None

    def test_urlentry_id_property(self):
        """The id property combines domain and key."""
        entry = NPMRC.URLEntry.from_values(
            "registry.example.com", "tokenHelper", "helper"
        )
        assert entry.id == "registry.example.com::tokenHelper"

    def test_urlentry_parse_basic(self):
        """Parse a basic .npmrc line."""
        entry = NPMRC.URLEntry("//registry.example.com/:tokenHelper=my-helper")
        assert entry._domain == "registry.example.com"
        assert entry._key == "tokenHelper"
        assert entry._value == "my-helper"

    def test_urlentry_parse_with_leading_whitespace(self):
        """Parse entry with leading whitespace."""
        entry = NPMRC.URLEntry("  //registry.example.com/:tokenHelper=value")
        # Note: there's a bug in the original code at line 46 that calculates _leading
        # incorrectly. It computes entry[:len(stripped_entry)-len(entry)] which gives
        # the entire entry string instead of just the whitespace.
        # This test documents current behavior, not ideal behavior.
        assert entry._domain == "registry.example.com"
        assert entry._key == "tokenHelper"
        assert entry._value == "value"

    def test_urlentry_parse_with_comment_semicolon(self):
        """Parse entry with trailing semicolon comment."""
        entry = NPMRC.URLEntry("//registry.example.com/:tokenHelper=value;comment here")
        assert entry._value == "value"

    def test_urlentry_parse_with_comment_hash(self):
        """Parse entry with trailing hash comment."""
        entry = NPMRC.URLEntry("//registry.example.com/:tokenHelper=value#comment here")
        assert entry._value == "value"

    def test_urlentry_parse_invalid_no_slashes(self):
        """Invalid entry must start with //."""
        with pytest.raises(ValueError, match="should start with"):
            NPMRC.URLEntry("registry.example.com/:tokenHelper=value")

    def test_urlentry_parse_invalid_missing_domain(self):
        """Invalid entry without domain."""
        with pytest.raises(ValueError, match="missing domain"):
            NPMRC.URLEntry("//:tokenHelper=value")

    def test_urlentry_parse_invalid_missing_key(self):
        """Invalid entry without key."""
        with pytest.raises(ValueError, match="missing key"):
            NPMRC.URLEntry("//registry.example.com/:=value")

    def test_urlentry_domain_with_trailing_slash(self):
        """Parse and normalize domain with trailing slash."""
        entry = NPMRC.URLEntry("//registry.example.com//:tokenHelper=value")
        assert entry._domain == "registry.example.com"

    def test_urlentry_contains_logic(self):
        """Test URLEntry containment for different values."""
        entry1 = NPMRC.URLEntry("//registry.example.com/:tokenHelper=helper1")
        entry2 = NPMRC.URLEntry("//registry.example.com/:tokenHelper=helper2")
        entry_none = NPMRC.URLEntry("//registry.example.com/:tokenHelper=")

        # Same entry is contained
        assert entry1 in [entry1]

        # Different value is not contained
        assert entry1 not in [entry2]

        # None value in entry matches any token
        assert entry_none not in [entry1]  # entry_none has no value


class TestNPMRC:
    """Tests for NPMRC class."""

    def test_npmrc_create_new_file(self):
        """Create a new NPMRC instance with non-existent file."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            npmrc = NPMRC(rc_path, modifiable=True)
            assert npmrc.modified is False
            assert npmrc.failures == 0

    def test_npmrc_context_manager_creates_file(self):
        """Using NPMRC as context manager creates file if modifiable."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True):
                assert rc_path.exists()

    def test_npmrc_context_manager_nonexistent_nonmodifiable(self):
        """Non-modifiable NPMRC doesn't create non-existent file."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=False):
                assert not rc_path.exists()

    def test_npmrc_parse_simple_file(self):
        """Parse a simple .npmrc file with multiple entries."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "//registry.npmjs.org/:tokenHelper=npm\n"
                "//npm.example.com/:tokenHelper=custom\n"
                "some_other_setting=value\n"
            )
            with NPMRC(rc_path, modifiable=False) as npmrc:
                assert len(npmrc._lines) == 3
                assert npmrc._mapping["registry.npmjs.org::tokenHelper"] == "npm"
                assert npmrc._mapping["npm.example.com::tokenHelper"] == "custom"

    def test_npmrc_parse_preserves_non_url_entries(self):
        """Parsing preserves non-URL entries as strings."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "registry=https://registry.npmjs.org/\n"
                "//registry.npmjs.org/:tokenHelper=npm\n"
            )
            with NPMRC(rc_path, modifiable=False) as npmrc:
                assert npmrc._lines[0] == "registry=https://registry.npmjs.org/"
                assert isinstance(npmrc._lines[1], NPMRC.URLEntry)

    def test_npmrc_add_entry(self):
        """Add a new entry to NPMRC."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                result = npmrc.add(entry)
                assert result is True
                assert npmrc.modified is True
                assert entry.id in npmrc._mapping

    def test_npmrc_add_duplicate_entry_fails(self):
        """Adding a duplicate entry returns False."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                assert npmrc.add(entry) is True
                assert npmrc.add(entry) is False
                assert npmrc.failures == 0

    def test_npmrc_add_conflict_with_authToken(self):
        """Adding tokenHelper when _authToken exists raises conflict error."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:_authToken=secret\n")
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                with pytest.raises(AuthKeyConflictError, match="_authToken"):
                    npmrc.add(entry)
                assert npmrc.failures == 1

    def test_npmrc_add_conflict_with_auth(self):
        """Adding tokenHelper when _auth exists raises conflict error."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:_auth=secret\n")
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                with pytest.raises(AuthKeyConflictError, match="_auth"):
                    npmrc.add(entry)
                assert npmrc.failures == 1

    def test_npmrc_add_conflict_with_password(self):
        """Adding tokenHelper when _password exists raises conflict error."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:_password=secret\n")
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                with pytest.raises(AuthKeyConflictError, match="_password"):
                    npmrc.add(entry)
                assert npmrc.failures == 1

    def test_npmrc_add_no_conflict_different_domain(self):
        """Adding tokenHelper to one domain doesn't conflict with _authToken on another."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//other.example.com/:_authToken=secret\n")
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                assert npmrc.add(entry) is True
                assert npmrc.failures == 0

    def test_npmrc_remove_entry(self):
        """Remove an entry from NPMRC."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=my-helper\n")
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                result = npmrc.remove(entry)
                assert result is True
                assert npmrc.modified is True
                assert entry.id not in npmrc._mapping

    def test_npmrc_remove_nonexistent_entry(self):
        """Removing non-existent entry returns False."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                result = npmrc.remove(entry)
                assert result is False
                assert npmrc.modified is False

    def test_npmrc_contains_urlentry(self):
        """Check if URLEntry is contained in NPMRC."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=my-helper\n")
            with NPMRC(rc_path, modifiable=False) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                assert entry in npmrc

    def test_npmrc_contains_string(self):
        """Check if string is contained in NPMRC."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("registry=https://registry.npmjs.org/\n")
            with NPMRC(rc_path, modifiable=False) as npmrc:
                assert "registry=https://registry.npmjs.org/" in npmrc

    def test_npmrc_write_modified_file(self):
        """Write modified NPMRC back to file."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "my-helper"
                )
                npmrc.add(entry)

            # Verify written content
            content = rc_path.read_text()
            assert "//registry.example.com/:tokenHelper=my-helper" in content

    def test_npmrc_write_not_modified_no_write(self):
        """Unmodified NPMRC is not written to file."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=existing\n")
            original_mtime = rc_path.stat().st_mtime

            # Read without modifying
            with NPMRC(rc_path, modifiable=True) as npmrc:
                pass

            # File should not be modified
            assert rc_path.stat().st_mtime == original_mtime
            assert not npmrc.modified

    def test_npmrc_write_nonmodifiable_no_write(self):
        """Non-modifiable NPMRC does not write."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "helper"
                )
                npmrc.add(entry)

            # Clear file
            rc_path.unlink()

            # Try to modify with non-modifiable instance
            with NPMRC(rc_path, modifiable=False) as npmrc:
                npmrc._modified = True  # Force modified flag

            # File should not exist
            assert not rc_path.exists()

    def test_npmrc_helped_hosts_single(self):
        """Get list of hosts with tokenHelper."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "//registry.npmjs.org/:tokenHelper=npm\n"
                "//npm.example.com/:tokenHelper=custom\n"
            )
            with NPMRC(rc_path, modifiable=False) as npmrc:
                hosts = npmrc.helped_hosts("npm")
                assert hosts == ["registry.npmjs.org"]

    def test_npmrc_helped_hosts_multiple(self):
        """Get list of hosts with same tokenHelper value."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "//registry1.example.com/:tokenHelper=my-helper\n"
                "//registry2.example.com/:tokenHelper=my-helper\n"
                "//registry3.example.com/:tokenHelper=other\n"
            )
            with NPMRC(rc_path, modifiable=False) as npmrc:
                hosts = npmrc.helped_hosts("my-helper")
                assert sorted(hosts) == [
                    "registry1.example.com",
                    "registry2.example.com",
                ]

    def test_npmrc_helped_hosts_empty(self):
        """Get empty list when no hosts use tokenHelper."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=other\n")
            with NPMRC(rc_path, modifiable=False) as npmrc:
                hosts = npmrc.helped_hosts("nonexistent")
                assert hosts == []

    def test_npmrc_roundtrip_preserves_format(self):
        """Writing and reading preserves file format."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_content = (
                "registry=https://registry.npmjs.org/\n"
                "//registry.example.com/:tokenHelper=my-helper\n"
                "  //custom.example.com/:_authToken=secret\n"
            )
            rc_path.write_text(original_content)

            # Read, add entry, write
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "new.example.com", "tokenHelper", "new"
                )
                npmrc.add(entry)

            # Read again
            content = rc_path.read_text()
            assert "registry=https://registry.npmjs.org/" in content
            assert "//custom.example.com/:_authToken=secret" in content
            assert "//new.example.com/:tokenHelper=new" in content

    def test_npmrc_create_if_not_exists(self):
        """Explicitly create NPMRC file if it doesn't exist."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            npmrc = NPMRC(rc_path, modifiable=True)
            assert not rc_path.exists()
            npmrc.create_if_not_exists()
            assert rc_path.exists()

    def test_npmrc_create_if_not_exists_already_exists(self):
        """Create if not exists doesn't fail if file already exists."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("existing content\n")
            npmrc = NPMRC(rc_path, modifiable=True)
            npmrc.create_if_not_exists()
            assert rc_path.read_text() == "existing content\n"

    def test_npmrc_multiple_operations(self):
        """Test multiple add/remove operations in sequence."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Add entries
                e1 = NPMRC.URLEntry.from_values("reg1.example.com", "tokenHelper", "h1")
                e2 = NPMRC.URLEntry.from_values("reg2.example.com", "tokenHelper", "h2")
                e3 = NPMRC.URLEntry.from_values("reg3.example.com", "tokenHelper", "h3")

                assert npmrc.add(e1) is True
                assert npmrc.add(e2) is True
                assert npmrc.add(e3) is True
                assert npmrc.modified is True

                # Remove middle entry
                assert npmrc.remove(e2) is True

                # Verify state
                assert e1.id in npmrc._mapping
                assert e2.id not in npmrc._mapping
                assert e3.id in npmrc._mapping

    def test_npmrc_failure_counter(self):
        """Failure counter increments on conflicts."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "//reg1.example.com/:_authToken=secret\n"
                "//reg2.example.com/:_password=pwd\n"
            )
            with NPMRC(rc_path, modifiable=True) as npmrc:
                assert npmrc.failures == 0

                e1 = NPMRC.URLEntry.from_values("reg1.example.com", "tokenHelper", "h1")
                try:
                    npmrc.add(e1)
                except AuthKeyConflictError:
                    pass
                assert npmrc.failures == 1

                e2 = NPMRC.URLEntry.from_values("reg2.example.com", "tokenHelper", "h2")
                try:
                    npmrc.add(e2)
                except AuthKeyConflictError:
                    pass
                assert npmrc.failures == 2


class TestAuthKeyConflictError:
    """Tests for AuthKeyConflictError exception."""

    def test_authkeyconflict_is_keyerror(self):
        """AuthKeyConflictError is a subclass of KeyError."""
        exc = AuthKeyConflictError("_authToken")
        assert isinstance(exc, KeyError)

    def test_authkeyconflict_message(self):
        """AuthKeyConflictError preserves message."""
        exc = AuthKeyConflictError("_auth")
        assert exc.args[0] == "_auth"
