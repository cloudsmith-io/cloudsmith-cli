"""Tests for the `cloudsmith repos privileges` commands."""

import json

import httpretty
import httpretty.core
import pytest

from ....cli.commands.main import main

API_HOST = "https://api.cloudsmith.io"
OWNER = "test-org"
REPO = "test-repo"
OWNER_REPO = f"{OWNER}/{REPO}"
PRIVILEGES_URL = f"{API_HOST}/repos/{OWNER}/{REPO}/privileges"
HERMETIC_ARGS = ["--api-key", "fake-api-key", "--api-host", API_HOST]
PRIVILEGES_COMMAND = ["repos", "privileges"]


@pytest.fixture(autouse=True)
def hermetic_environment(monkeypatch):
    """Keep stray environment/config from influencing these commands.

    An inherited CLOUDSMITH_ORG/CLOUDSMITH_API_HOST would change which host
    or org the command resolves to without the test noticing.
    """
    monkeypatch.delenv("CLOUDSMITH_ORG", raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_HOST", raising=False)
    monkeypatch.delenv("CLOUDSMITH_API_KEY", raising=False)
    monkeypatch.setattr(
        httpretty.core.fakesock.socket,
        "shutdown",
        lambda self, how: None,
        raising=False,
    )


def register_list(privileges, status=200):
    """Register a GET response holding the given privileges."""
    httpretty.register_uri(
        httpretty.GET,
        PRIVILEGES_URL,
        body=json.dumps({"privileges": privileges}),
        status=status,
        content_type="application/json",
    )


def register_write(method, status=200, body=None):
    """Register a PATCH/PUT response for the privileges endpoint."""
    httpretty.register_uri(
        method,
        PRIVILEGES_URL,
        body=json.dumps(body) if body is not None else "",
        status=status,
        content_type="application/json",
    )


def last_request_body():
    """Get the JSON body of the last request httpretty captured."""
    return json.loads(httpretty.last_request().body.decode("utf-8"))


class TestPrivilegesList:
    @httpretty.activate(allow_net_connect=False)
    def test_lists_privileges_by_type_and_name(self, runner):
        register_list(
            [
                {"privilege": "Read", "team": None, "user": "alice", "service": None},
                {"privilege": "Admin", "team": None, "user": None, "service": "ci"},
                {"privilege": "Write", "team": "eng", "user": None, "service": None},
            ]
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["list"] + HERMETIC_ARGS + [OWNER_REPO],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Getting list of repository privileges" in result.output
        assert "Type" in result.output and "Name" in result.output
        # Sorted by type then name, so service/team/user in that order.
        rows = [
            line
            for line in result.output.splitlines()
            if line.startswith(("Service", "Team", "User"))
        ]
        assert [row.split("|")[0].strip() for row in rows] == [
            "Service",
            "Team",
            "User",
        ]
        assert "Results: 3 privileges" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_singular_result_count(self, runner):
        register_list([{"privilege": "Read", "team": "eng"}])

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["list"] + HERMETIC_ARGS + [OWNER_REPO],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Results: 1 privilege\n" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_empty_list(self, runner):
        register_list([])

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["list"] + HERMETIC_ARGS + [OWNER_REPO],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Results: 0 privileges" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_json_output_is_clean_on_stdout(self, runner):
        register_list([{"privilege": "Read", "team": "eng"}])

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["list"] + HERMETIC_ARGS + ["-F", "json", OWNER_REPO],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        # The progress message goes to stderr in JSON mode, so stdout on its
        # own has to be a single valid document a script can parse.
        payload = json.loads(result.stdout)
        assert payload["data"] == [
            {"privilege": "Read", "team": "eng", "user": None, "service": None}
        ]

    @httpretty.activate(allow_net_connect=False)
    def test_group_and_command_aliases(self, runner):
        register_list([{"privilege": "Read", "team": "eng"}])

        result = runner.invoke(
            main,
            ["repos", "privilege", "ls"] + HERMETIC_ARGS + [OWNER_REPO],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Results: 1 privilege" in result.output

    def test_no_page_options(self, runner):
        """The endpoint returns everything at once, so paging isn't offered."""
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["list", "--help"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "--page" not in result.output


class TestPrivilegesSet:
    @httpretty.activate(allow_net_connect=False)
    def test_grants_to_several_targets_in_one_call(self, runner):
        register_list([])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [
                OWNER_REPO,
                "--team",
                "eng",
                "--user",
                "alice",
                "--service",
                "ci",
                "--privilege",
                "write",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert last_request_body() == {
            "privileges": [
                {"privilege": "Write", "team": "eng"},
                {"privilege": "Write", "user": "alice"},
                {"privilege": "Write", "service": "ci"},
            ]
        }
        assert (
            f"Granting Write on {REPO} in the {OWNER} namespace to "
            "team eng, user alice, service ci" in result.output
        )
        assert "Results: 3 privileges" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_privilege_is_case_insensitive_and_echoed_in_api_casing(self, runner):
        register_list([])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "ADMIN"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert last_request_body()["privileges"] == [
            {"privilege": "Admin", "team": "eng"}
        ]
        assert "Granting Admin" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_lowering_an_existing_privilege_asks_first(self, runner):
        """The endpoint sets a level in either direction, so this can revoke."""
        register_list([{"privilege": "Admin", "team": "eng"}])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "read"],
            input="y\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            f"Lower team eng from Admin to Read on {REPO} in the {OWNER} namespace?"
            in result.output
        )
        assert last_request_body()["privileges"] == [
            {"privilege": "Read", "team": "eng"}
        ]

    @httpretty.activate(allow_net_connect=False)
    def test_declining_the_lowering_writes_nothing(self, runner):
        register_list([{"privilege": "Admin", "team": "eng"}])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "read"],
            input="n\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert httpretty.last_request().method == "GET"

    @httpretty.activate(allow_net_connect=False)
    def test_raising_an_existing_privilege_never_asks(self, runner):
        register_list([{"privilege": "Read", "team": "eng"}])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "admin"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Lower" not in result.output
        assert last_request_body()["privileges"] == [
            {"privilege": "Admin", "team": "eng"}
        ]

    @httpretty.activate(allow_net_connect=False)
    def test_setting_the_same_level_never_asks(self, runner):
        register_list([{"privilege": "Write", "team": "eng"}])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "write"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Lower" not in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_only_the_lowered_targets_are_named(self, runner):
        register_list(
            [
                {"privilege": "Admin", "team": "eng"},
                {"privilege": "Read", "user": "alice"},
            ]
        )
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [
                OWNER_REPO,
                "--team",
                "eng",
                "--user",
                "alice",
                "--service",
                "ci",
                "--privilege",
                "write",
            ],
            input="y\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Lower team eng from Admin to Write" in result.output
        assert "alice" not in result.output.split("namespace?")[0]

    @httpretty.activate(allow_net_connect=False)
    def test_yes_skips_the_lowering_prompt(self, runner):
        register_list([{"privilege": "Admin", "team": "eng"}])
        register_write(httpretty.PATCH)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "read", "-y"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Lower" not in result.output
        assert last_request_body()["privileges"] == [
            {"privilege": "Read", "team": "eng"}
        ]

    def test_rejects_an_unknown_privilege(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "Owner"],
        )

        assert result.exit_code != 0
        assert "'Owner' is not one of 'read', 'write', 'admin'" in result.output

    def test_requires_at_least_one_target(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--privilege", "read"],
        )

        assert result.exit_code != 0
        assert "Specify at least one of --team, --user or --service." in result.output

    def test_rejects_a_repeated_target(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--team", "eng", "--privilege", "read"],
        )

        assert result.exit_code != 0
        assert "Specified more than once: team eng." in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_api_rejection_is_one_sentence(self, runner):
        register_list([])
        register_write(
            httpretty.PATCH,
            status=422,
            body={
                "detail": "Invalid input.",
                "fields": {
                    "privileges": "Invalid team(s) specified ['no-such-team']",
                },
            },
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "no-such-team", "--privilege", "read"],
        )

        # AliasGroup.main runs click with standalone_mode=False, so the exit
        # code comes back as the return value rather than via SystemExit.
        assert result.return_value == 422
        assert (
            f"Could not set privileges for {REPO}: "
            "invalid team(s) specified ['no-such-team']" in result.output
        )
        assert "Privileges Field:" not in result.output
        assert "status: 422" not in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_other_statuses_keep_the_status_code(self, runner):
        register_list([])
        register_write(
            httpretty.PATCH,
            status=403,
            body={"detail": "You do not have permission to perform this action."},
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "read"],
        )

        assert result.return_value == 403
        assert "status: 403" in result.output
        assert "Could not set privileges" not in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_a_leading_acronym_keeps_its_casing(self, runner):
        register_list([])
        register_write(
            httpretty.PATCH,
            status=422,
            body={"detail": "Invalid input.", "fields": {"privileges": "URL rejected"}},
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "read"],
        )

        assert f"Could not set privileges for {REPO}: URL rejected" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_a_422_without_fields_keeps_the_status_code(self, runner):
        """`detail` falls back to the status description, which reads badly."""
        register_list([])
        register_write(httpretty.PATCH, status=422, body={})

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--privilege", "read"],
        )

        assert result.return_value == 422
        assert "status: 422" in result.output
        assert "unprocessable" not in result.output.lower().split("status: 422")[0]

    @httpretty.activate(allow_net_connect=False)
    def test_summarised_error_in_json_mode(self, runner):
        register_list([])
        register_write(
            httpretty.PATCH,
            status=422,
            body={
                "detail": "Invalid input.",
                "fields": {"privileges": "Invalid team(s) specified ['nope']"},
            },
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "nope", "--privilege", "read", "-F", "json"],
        )

        payload = json.loads(result.stdout)
        assert payload["detail"] == (
            f"Could not set privileges for {REPO}: invalid team(s) specified ['nope']"
        )

    def test_rejects_an_empty_target_name(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["set"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "", "--privilege", "read"],
        )

        assert result.exit_code != 0
        assert "Specify a slug for --team." in result.output


class TestPrivilegesRevoke:
    @httpretty.activate(allow_net_connect=False)
    def test_revokes_named_targets_and_keeps_the_rest(self, runner):
        register_list(
            [
                {"privilege": "Write", "team": "eng", "user": None, "service": None},
                {"privilege": "Read", "team": None, "user": "alice", "service": None},
            ]
        )
        register_write(httpretty.PUT)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng"],
            input="y\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            f"Revoke the privileges of team eng on {REPO} in the {OWNER} namespace?"
            in result.output
        )
        assert "Are you absolutely certain" not in result.output
        # The listed entries carry a null for every kind that doesn't apply,
        # and the write endpoint rejects those nulls, so they're dropped.
        assert last_request_body() == {
            "privileges": [{"privilege": "Read", "user": "alice"}]
        }
        assert "Results: 1 privilege" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_skips_targets_without_an_explicit_privilege(self, runner):
        register_list(
            [{"privilege": "Write", "team": "eng", "user": None, "service": None}]
        )
        register_write(httpretty.PUT)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "--user", "someone-else", "-y"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "No explicit privilege for user someone-else, skipping." in result.output
        assert last_request_body() == {"privileges": []}

    @httpretty.activate(allow_net_connect=False)
    def test_second_run_is_a_no_op(self, runner):
        register_list([])

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "-y"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "No explicit privilege for team eng, skipping." in result.output
        assert "Nothing to revoke." in result.output
        assert httpretty.last_request().method == "GET"

    @httpretty.activate(allow_net_connect=False)
    def test_declining_the_prompt_writes_nothing(self, runner):
        register_list(
            [{"privilege": "Write", "team": "eng", "user": None, "service": None}]
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng"],
            input="n\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert httpretty.last_request().method == "GET"

    @httpretty.activate(allow_net_connect=False)
    def test_api_rejection_names_the_revoke(self, runner):
        register_list([{"privilege": "Read", "team": "eng"}])
        register_write(
            httpretty.PUT,
            status=422,
            body={"detail": "Invalid input.", "fields": {"privileges": "Nope"}},
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "-y"],
        )

        assert f"Could not revoke privileges for {REPO}: nope" in result.output

    def test_requires_at_least_one_target(self, runner):
        result = runner.invoke(
            main, PRIVILEGES_COMMAND + ["revoke"] + HERMETIC_ARGS + [OWNER_REPO]
        )

        assert result.exit_code != 0
        assert "Specify at least one of --team, --user or --service." in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_no_op_still_emits_a_json_document(self, runner):
        """A `-F json` consumer must get something to parse on every path."""
        register_list([{"privilege": "Read", "team": "eng"}])

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--user", "nobody", "-y", "-F", "json"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        # The same compact shape the success path emits, so a consumer sees
        # one entry shape whichever path ran.
        assert json.loads(result.stdout)["data"] == [
            {"privilege": "Read", "team": "eng"}
        ]

    @httpretty.activate(allow_net_connect=False)
    def test_declining_writes_and_says_nothing(self, runner):
        register_list([{"privilege": "Read", "team": "eng"}])

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "-F", "json"],
            input="n\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.stdout == ""
        assert httpretty.last_request().method == "GET"

    @httpretty.activate(allow_net_connect=False)
    def test_refuses_when_it_cannot_read_a_current_privilege(self, runner):
        """Writing the list back would drop what the CLI can't express."""
        register_list(
            [
                {"privilege": "Write", "team": "eng", "user": None, "service": None},
                {"privilege": "Read", "team": None, "user": None, "service": None},
            ]
        )
        register_write(httpretty.PUT)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["revoke"]
            + HERMETIC_ARGS
            + [OWNER_REPO, "--team", "eng", "-y"],
        )

        assert result.exit_code != 0
        assert "doesn't understand" in result.output
        assert "privileges replace" in result.output
        assert httpretty.last_request().method == "GET"


class TestPrivilegesReplace:
    @httpretty.activate(allow_net_connect=False)
    def test_replaces_from_a_file(self, runner, tmp_path):
        register_write(httpretty.PUT)
        path = tmp_path / "privileges.json"
        path.write_text(
            json.dumps(
                {
                    "privileges": [
                        {"team": "eng", "privilege": "Write"},
                        {"user": "alice", "privilege": "read"},
                    ]
                }
            )
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, str(path)],
            input="y\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            f"Replace all 2 privileges on {REPO} in the {OWNER} namespace, "
            "removing any not listed?" in result.output
        )
        assert "Are you absolutely certain" not in result.output
        assert last_request_body() == {
            "privileges": [
                {"privilege": "Write", "team": "eng"},
                {"privilege": "Read", "user": "alice"},
            ]
        }

    @httpretty.activate(allow_net_connect=False)
    def test_accepts_a_bare_list_on_stdin(self, runner):
        register_write(httpretty.PUT)

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps([{"service": "ci", "privilege": "admin"}]),
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert last_request_body() == {
            "privileges": [{"privilege": "Admin", "service": "ci"}]
        }

    def test_rejects_an_entry_naming_two_kinds(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps([{"team": "eng", "user": "alice", "privilege": "read"}]),
        )

        assert result.exit_code != 0
        assert "Invalid value for PRIVILEGES_FILE" in result.output
        assert (
            "Each privilege needs exactly one of 'team', 'user' or 'service'."
            in result.output
        )

    def test_rejects_an_unknown_privilege(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps([{"team": "eng", "privilege": "Owner"}]),
        )

        assert result.exit_code != 0
        assert "'Owner' is not one of 'read', 'write', 'admin'." in result.output

    def test_stdin_without_yes_is_refused(self, runner):
        """The document and the y/N answer would come from the same stream."""
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-"],
            input=json.dumps([{"team": "eng", "privilege": "read"}]),
        )

        assert result.exit_code != 0
        assert "Pass -y to confirm up front." in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_an_empty_file_says_it_revokes_everything(self, runner, tmp_path):
        register_write(httpretty.PUT)
        path = tmp_path / "privileges.json"
        path.write_text("[]")

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, str(path)],
            input="y\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            "The file lists no privileges. Revoke all explicit access to "
            f"{REPO} in the {OWNER} namespace?" in result.output
        )
        assert "Replace all 0 privileges" not in result.output
        assert last_request_body() == {"privileges": []}

    def test_rejects_a_non_object_entry(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps(["eng"]),
        )

        assert result.exit_code != 0
        assert "Each privilege must be an object." in result.output

    def test_rejects_a_document_that_is_not_a_list(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps({"teams": []}),
        )

        assert result.exit_code != 0
        assert "Expected a list of privileges" in result.output

    def test_rejects_a_non_string_name(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps([{"team": 123, "privilege": "read"}]),
        )

        assert result.exit_code != 0
        assert "The 'team' of a privilege must be a slug, not 123." in result.output

    def test_rejects_a_repeated_target(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps(
                [
                    {"team": "eng", "privilege": "read"},
                    {"team": "eng", "privilege": "admin"},
                ]
            ),
        )

        assert result.exit_code != 0
        assert "Specified more than once: team eng." in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_api_rejection_names_the_replace(self, runner):
        register_write(
            httpretty.PUT,
            status=422,
            body={"detail": "Invalid input.", "fields": {"privileges": "Nope"}},
        )

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input=json.dumps([{"team": "eng", "privilege": "read"}]),
        )

        assert f"Could not replace privileges for {REPO}: nope" in result.output

    @httpretty.activate(allow_net_connect=False)
    def test_declining_writes_and_says_nothing(self, runner, tmp_path):
        register_write(httpretty.PUT)
        path = tmp_path / "privileges.json"
        path.write_text(json.dumps([{"team": "eng", "privilege": "read"}]))

        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND
            + ["replace"]
            + HERMETIC_ARGS
            + [OWNER_REPO, str(path), "-F", "json"],
            input="n\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.stdout == ""
        assert httpretty.has_request() is False

    def test_rejects_invalid_json(self, runner):
        result = runner.invoke(
            main,
            PRIVILEGES_COMMAND + ["replace"] + HERMETIC_ARGS + [OWNER_REPO, "-", "-y"],
            input="not json",
        )

        assert result.exit_code != 0
        assert "Invalid JSON" in result.output
