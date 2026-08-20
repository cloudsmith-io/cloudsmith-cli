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
        assert entry._leading == "  "
        assert entry._domain == "registry.example.com"
        assert entry._key == "tokenHelper"
        assert entry._value == "value"
        assert str(entry) == "  //registry.example.com/:tokenHelper=value"

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

    def test_npmrc_parse_ignores_invalid_lines(self):
        """Parsing gracefully skips invalid URL lines.

        Invalid lines that start with // but don't parse correctly are stored
        as raw strings and not added to the mapping. This prevents crashes
        on malformed entries while preserving the original content.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "//registry.npmjs.org/:tokenHelper=npm\n"
                "// malformed comment line\n"
                "//missing-domain/\n"
                "//example.com/:validKey=validValue\n"
                "//domain.com/noKeyValuePair\n"
            )
            # Should parse without raising an exception
            with NPMRC(rc_path, modifiable=False) as npmrc:
                # Should have 5 lines total
                assert len(npmrc._lines) == 5

                # Valid entries should be URLEntry objects
                assert isinstance(npmrc._lines[0], NPMRC.URLEntry)
                assert isinstance(npmrc._lines[3], NPMRC.URLEntry)

                # Invalid entries should be stored as strings
                assert isinstance(npmrc._lines[1], str)
                assert isinstance(npmrc._lines[2], str)
                assert isinstance(npmrc._lines[4], str)
                assert npmrc._lines[1] == "// malformed comment line"
                assert npmrc._lines[2] == "//missing-domain/"
                assert npmrc._lines[4] == "//domain.com/noKeyValuePair"

                # Only valid entries should be in mapping
                assert len(npmrc._mapping) == 2
                assert "registry.npmjs.org::tokenHelper" in npmrc._mapping
                assert "example.com::validKey" in npmrc._mapping

    def test_npmrc_parse_user_comment_line(self):
        """Parsing handles user-entered comment-like lines gracefully.

        This is the specific case from the PR comment where a user mistakenly
        thought // was for comments (like in other formats) and created a
        malformed entry "// oh I thought // was for code comments".
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "// oh I thought // was for code comments\n"
                "//npm.cloudsmith.io/:tokenHelper=/usr/local/bin/npm-cred\n"
            )
            # Should not raise ValueError during parsing
            with NPMRC(rc_path, modifiable=False) as npmrc:
                assert len(npmrc._lines) == 2

                # First line (malformed) should be stored as string
                assert isinstance(npmrc._lines[0], str)
                assert npmrc._lines[0] == "// oh I thought // was for code comments"

                # Second line (valid) should be parsed
                assert isinstance(npmrc._lines[1], NPMRC.URLEntry)
                assert npmrc._lines[1]._domain == "npm.cloudsmith.io"
                assert npmrc._lines[1]._key == "tokenHelper"

                # Only the valid entry should be in mapping
                assert len(npmrc._mapping) == 1
                assert "npm.cloudsmith.io::tokenHelper" in npmrc._mapping

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

    def test_npmrc_add_entry_preserves_invalid_lines(self):
        """Adding an entry preserves invalid lines in the file.

        When adding a new entry to a file with invalid lines, those invalid
        lines should be preserved in their original position and written back
        to the file unchanged.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "// invalid comment line\n"
                "//registry.npmjs.org/:tokenHelper=existing\n"
                "//malformed/missing/content\n"
            )
            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Add a new valid entry
                new_entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "new-helper"
                )
                assert npmrc.add(new_entry) is True

                # Verify the lines are in order: invalid, valid, invalid, new valid
                assert len(npmrc._lines) == 4
                assert isinstance(npmrc._lines[0], str)
                assert npmrc._lines[0] == "// invalid comment line"
                assert isinstance(npmrc._lines[1], NPMRC.URLEntry)
                assert isinstance(npmrc._lines[2], str)
                assert npmrc._lines[2] == "//malformed/missing/content"
                assert isinstance(npmrc._lines[3], NPMRC.URLEntry)

            # Verify the file content preserves all lines including invalid ones
            content = rc_path.read_text()
            assert "// invalid comment line" in content
            assert "//registry.npmjs.org/:tokenHelper=existing" in content
            assert "//malformed/missing/content" in content
            assert "//registry.example.com/:tokenHelper=new-helper" in content

    def test_npmrc_remove_entry_preserves_invalid_lines(self):
        """Removing an entry preserves invalid lines in the file.

        When removing a valid entry from a file with invalid lines, those
        invalid lines should remain in place and be written back unchanged.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "// this is not a valid entry\n"
                "//registry.example.com/:tokenHelper=helper1\n"
                "//registry.other.com/:tokenHelper=helper2\n"
                "//another invalid line without proper format\n"
            )
            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Remove the first valid entry
                entry_to_remove = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "helper1"
                )
                assert npmrc.remove(entry_to_remove) is True

                # Verify structure: invalid, removed, valid, invalid
                assert len(npmrc._lines) == 3  # removed one valid entry
                assert isinstance(npmrc._lines[0], str)
                assert npmrc._lines[0] == "// this is not a valid entry"
                assert isinstance(npmrc._lines[1], NPMRC.URLEntry)
                assert npmrc._lines[1]._domain == "registry.other.com"
                assert isinstance(npmrc._lines[2], str)
                assert npmrc._lines[2] == "//another invalid line without proper format"

            # Verify the file content preserves invalid lines
            content = rc_path.read_text()
            assert "// this is not a valid entry" in content
            assert (
                "//registry.example.com/:tokenHelper=helper1" not in content
            )  # removed
            assert "//registry.other.com/:tokenHelper=helper2" in content
            assert "//another invalid line without proper format" in content

    def test_npmrc_add_and_remove_preserves_invalid_lines_roundtrip(self):
        """Adding and removing entries in sequence preserves invalid lines.

        This test validates that the file can be modified multiple times
        while preserving invalid entries throughout the process.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "// user comment\n//registry.a.com/:tokenHelper=a\n//malformed\n"
            )

            # First pass: add and remove
            with NPMRC(rc_path, modifiable=True) as npmrc:
                new_entry = NPMRC.URLEntry.from_values(
                    "registry.b.com", "tokenHelper", "b"
                )
                npmrc.add(new_entry)

            # Verify file has invalid lines preserved
            content = rc_path.read_text()
            assert "// user comment" in content
            assert "//malformed" in content

            # Second pass: read again and verify structure
            with NPMRC(rc_path, modifiable=False) as npmrc:
                assert len(npmrc._lines) == 4  # 2 invalid + 2 valid
                invalid_count = sum(
                    1 for line in npmrc._lines if not isinstance(line, NPMRC.URLEntry)
                )
                valid_count = sum(
                    1 for line in npmrc._lines if isinstance(line, NPMRC.URLEntry)
                )
                assert invalid_count == 2
                assert valid_count == 2

    def test_npmrc_add_update_existing_entry_modifies_lines(self):
        """Updating an existing entry modifies the _lines list in place.

        When adding an entry with the same domain and key but different value,
        the entry in _lines should be replaced with the new entry object.
        This ensures that __str__() returns the updated value.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=/old/path/helper\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Verify initial state
                assert len(npmrc._lines) == 1
                old_entry = npmrc._lines[0]
                assert isinstance(old_entry, NPMRC.URLEntry)
                assert old_entry._value == "/old/path/helper"

                # Add a new entry with same domain/key but different value
                new_entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "/new/path/helper"
                )
                result = npmrc.add(new_entry)

                # Verify operation returned True
                assert result is True

                # Verify _lines was updated with the new entry object
                assert len(npmrc._lines) == 1
                updated_entry = npmrc._lines[0]
                assert isinstance(updated_entry, NPMRC.URLEntry)
                assert updated_entry is new_entry, (
                    "_lines should contain the new entry object, not the old one"
                )
                assert updated_entry._value == "/new/path/helper"

    def test_npmrc_add_update_sets_modified_flag(self):
        """Updating an existing entry sets the _modified flag to True."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=/old/path/helper\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Verify initial state
                assert npmrc.modified is False

                # Update the entry
                new_entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "/new/path/helper"
                )
                npmrc.add(new_entry)

                # Verify _modified flag was set
                assert npmrc.modified is True

    def test_npmrc_add_update_syncs_mapping(self):
        """Updating an entry keeps _mapping in sync with _lines.

        When an entry is updated, the mapping value should reflect the new value.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("//registry.example.com/:tokenHelper=/old/path/helper\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Verify initial mapping
                entry_id = "registry.example.com::tokenHelper"
                assert npmrc._mapping[entry_id] == "/old/path/helper"

                # Update the entry
                new_entry = NPMRC.URLEntry.from_values(
                    "registry.example.com", "tokenHelper", "/new/path/helper"
                )
                npmrc.add(new_entry)

                # Verify mapping was updated
                assert npmrc._mapping[entry_id] == "/new/path/helper"

    def test_npmrc_add_update_multiple_entries(self):
        """Updating one entry doesn't affect others in _lines.

        Verifies that when multiple tokenHelper entries exist and one is updated,
        only the matching entry is replaced while others are preserved.
        """
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "//registry.a.com/:tokenHelper=/old/path/helper\n"
                "//registry.b.com/:tokenHelper=/other/path/helper\n"
            )

            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Verify initial state
                assert len(npmrc._lines) == 2
                entry_a = npmrc._lines[0]
                assert isinstance(entry_a, NPMRC.URLEntry)
                entry_b = npmrc._lines[1]
                assert isinstance(entry_b, NPMRC.URLEntry)
                assert entry_a._domain == "registry.a.com"
                assert entry_b._domain == "registry.b.com"

                # Update only registry.a.com
                new_entry_a = NPMRC.URLEntry.from_values(
                    "registry.a.com", "tokenHelper", "/new/path/helper"
                )
                result = npmrc.add(new_entry_a)

                # Verify update was successful
                assert result is True

                # Verify _lines structure: updated a, unchanged b
                assert len(npmrc._lines) == 2
                assert npmrc._lines[0] is new_entry_a
                assert npmrc._lines[0]._value == "/new/path/helper"
                assert npmrc._lines[1] is entry_b  # Unchanged
                assert npmrc._lines[1]._value == "/other/path/helper"

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


class TestInstallingAndUninstallingWithRealWorldConfigs:
    """Integration tests with realistic pre-configured .npmrc files."""

    def test_install_appends_line_to_minimal_npmrc(self):
        """Installing appends tokenHelper line to minimal .npmrc."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("registry=https://registry.npmjs.org/\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "npm.cloudsmith.io",
                    "tokenHelper",
                    "/usr/local/bin/npm-credentials-cloudsmith",
                )
                assert npmrc.add(entry) is True

            # Verify file content - check exact lines
            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]  # exclude empty
            assert len(lines) == 2
            assert lines[0] == "registry=https://registry.npmjs.org/"
            assert (
                lines[1]
                == "//npm.cloudsmith.io/:tokenHelper=/usr/local/bin/npm-credentials-cloudsmith"
            )

    def test_install_preserves_all_other_lines(self):
        """Installing preserves all non-related lines in .npmrc."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "legacy-peer-deps=true",
                "@myorg:registry=https://custom.example.com/",
                "//custom.example.com/:always-auth=true",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "npm.cloudsmith.io",
                    "tokenHelper",
                    "/usr/local/bin/npm-credentials-cloudsmith",
                )
                assert npmrc.add(entry) is True

            # Verify all original lines are still there (exact match)
            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            for original_line in original_lines:
                assert original_line in lines
            assert (
                "//npm.cloudsmith.io/:tokenHelper=/usr/local/bin/npm-credentials-cloudsmith"
                in lines
            )

    def test_uninstall_removes_only_target_line(self):
        """Uninstalling removes only the target tokenHelper line."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "//npm.cloudsmith.io/:tokenHelper=/usr/local/bin/npm-credentials-cloudsmith",
                "legacy-peer-deps=true",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "npm.cloudsmith.io",
                    "tokenHelper",
                    "/usr/local/bin/npm-credentials-cloudsmith",
                )
                assert npmrc.remove(entry) is True

            # Verify only the target line was removed
            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            assert "registry=https://registry.npmjs.org/" in lines
            assert "legacy-peer-deps=true" in lines
            assert not any("//npm.cloudsmith.io/:tokenHelper" in line for line in lines)

    def test_install_multiple_registries_preserves_order(self):
        """Installing multiple registries preserves existing order."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "//registry1.example.com/:always-auth=true",
                "//registry2.example.com/:always-auth=true",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry1 = NPMRC.URLEntry.from_values(
                    "cloudsmith1.io", "tokenHelper", "/path/to/helper1"
                )
                entry2 = NPMRC.URLEntry.from_values(
                    "cloudsmith2.io", "tokenHelper", "/path/to/helper2"
                )
                assert npmrc.add(entry1) is True
                assert npmrc.add(entry2) is True

            # Verify original lines are in original order, new lines at end
            lines = [line for line in rc_path.read_text().split("\n") if line]
            assert lines[0] == "registry=https://registry.npmjs.org/"
            assert lines[1] == "//registry1.example.com/:always-auth=true"
            assert lines[2] == "//registry2.example.com/:always-auth=true"
            assert lines[3] == "//cloudsmith1.io/:tokenHelper=/path/to/helper1"
            assert lines[4] == "//cloudsmith2.io/:tokenHelper=/path/to/helper2"

    def test_install_then_uninstall_leaves_clean_state(self):
        """Installing then uninstalling returns file to original state."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "//registry.npmjs.org/:_authToken=secret",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            # Install
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/helper"
                )
                assert npmrc.add(entry) is True

            content_after_install = rc_path.read_text()
            lines_after_install = [
                line for line in content_after_install.split("\n") if line
            ]
            assert "//cloudsmith.io/:tokenHelper=/path/helper" in lines_after_install

            # Uninstall
            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/helper"
                )
                assert npmrc.remove(entry) is True

            content_after_uninstall = rc_path.read_text()
            lines_after_uninstall = [
                line for line in content_after_uninstall.split("\n") if line
            ]
            # Verify all original lines are still present (exact match)
            for original_line in original_lines:
                assert original_line in lines_after_uninstall
            # Verify cloudsmith entry was removed
            assert not any(
                "//cloudsmith.io/:tokenHelper" in line for line in lines_after_uninstall
            )

    def test_install_with_scoped_packages(self):
        """Installing works alongside scoped package registries."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "@myorg:registry=https://custom.example.com/",
                "@another:registry=https://another.example.com/",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/helper"
                )
                assert npmrc.add(entry) is True

            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            # All scoped registries should still be there
            assert "@myorg:registry=https://custom.example.com/" in lines
            assert "@another:registry=https://another.example.com/" in lines
            assert "//cloudsmith.io/:tokenHelper=/path/helper" in lines

    def test_install_with_commented_lines(self):
        """Installing preserves commented-out lines."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "# //old.registry.com/:_authToken=disabled",
                "legacy-peer-deps=true",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/helper"
                )
                assert npmrc.add(entry) is True

            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            # Commented line should be preserved (exact match)
            assert "# //old.registry.com/:_authToken=disabled" in lines
            assert "//cloudsmith.io/:tokenHelper=/path/helper" in lines

    def test_uninstall_idempotent(self):
        """Uninstalling same entry twice is safe (idempotent)."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "//cloudsmith.io/:tokenHelper=/path/helper",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/helper"
                )
                # First removal succeeds
                assert npmrc.remove(entry) is True
                # Second removal returns False (already removed)
                assert npmrc.remove(entry) is False

    def test_install_with_complex_registry_config(self):
        """Installing to complex real-world registry configuration."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "npm_config_loglevel=warn",
                "@babel:registry=https://registry.npmjs.org/",
                "@types:registry=https://registry.npmjs.org/",
                "//registry.npmjs.org/:_authToken=npm_secret_token_here",
                "always-auth=false",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                cloudsmith_entry = NPMRC.URLEntry.from_values(
                    "npm.cloudsmith.io",
                    "tokenHelper",
                    "/usr/local/bin/npm-credentials-cloudsmith",
                )
                assert npmrc.add(cloudsmith_entry) is True

            # Verify after context manager exit
            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            # Original auth still there
            assert "//registry.npmjs.org/:_authToken=npm_secret_token_here" in lines
            # New entry added
            assert (
                "//npm.cloudsmith.io/:tokenHelper=/usr/local/bin/npm-credentials-cloudsmith"
                in lines
            )
            # All original lines preserved
            for original_line in original_lines:
                assert original_line in lines

    def test_install_different_helpers_same_domain(self):
        """Installing different credential helpers to same domain."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text("registry=https://registry.npmjs.org/\n")

            with NPMRC(rc_path, modifiable=True) as npmrc:
                # Add tokenHelper for cloudsmith
                entry1 = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/to/helper1"
                )
                assert npmrc.add(entry1) is True

                # Add custom setting for same domain
                entry2 = NPMRC.URLEntry.from_values(
                    "cloudsmith.io",
                    "registryUrl",
                    "https://cloudsmith.io/npm/myorg/myrepo/",
                )
                assert npmrc.add(entry2) is True

            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            assert "//cloudsmith.io/:tokenHelper=/path/to/helper1" in lines
            assert (
                "//cloudsmith.io/:registryUrl=https://cloudsmith.io/npm/myorg/myrepo/"
                in lines
            )

    def test_roundtrip_with_leading_whitespace(self):
        """Roundtrip preserves leading whitespace on entries."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            original_lines = [
                "registry=https://registry.npmjs.org/",
                "  //indented.example.com/:_authToken=secret",
            ]
            rc_path.write_text("\n".join(original_lines) + "\n")

            # Read and re-write without changes
            with NPMRC(rc_path, modifiable=True):
                # Don't modify, just read
                pass

            content = rc_path.read_text()
            lines = content.split("\n")
            # Indentation should be preserved (exact match)
            assert "  //indented.example.com/:_authToken=secret" in lines

    def test_install_with_empty_lines(self):
        """Installing handles .npmrc with empty lines gracefully."""
        with TemporaryDirectory() as tmpdir:
            rc_path = Path(tmpdir) / ".npmrc"
            rc_path.write_text(
                "registry=https://registry.npmjs.org/\n\nlegacy-peer-deps=true\n\n"
            )

            with NPMRC(rc_path, modifiable=True) as npmrc:
                entry = NPMRC.URLEntry.from_values(
                    "cloudsmith.io", "tokenHelper", "/path/helper"
                )
                assert npmrc.add(entry) is True

            content = rc_path.read_text()
            lines = [line for line in content.split("\n") if line]
            # All non-empty content preserved
            assert "registry=https://registry.npmjs.org/" in lines
            assert "legacy-peer-deps=true" in lines
            assert "//cloudsmith.io/:tokenHelper=/path/helper" in lines
