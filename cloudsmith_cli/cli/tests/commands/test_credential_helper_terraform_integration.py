# Copyright 2026 Cloudsmith Ltd
"""Live integration test for the Terraform credentials helper.

This is the end-to-end check the unit tests cannot make: that a real
``terraform init`` authenticates against a Cloudsmith Terraform registry using
*only* the ``terraform-credentials-cloudsmith`` helper, with no token on disk.

It is intentionally minimal — it proves authentication and nothing else. It
does not assert a module is downloaded (that would couple the test to specific
registry contents); it asserts that Terraform's module installation was *not*
rejected for authentication reasons, which is the one thing the helper is
responsible for.

Requires:
    * ``terraform`` on PATH (skipped otherwise).
    * ``terraform-credentials-cloudsmith`` on PATH — i.e. cloudsmith-cli
      installed as a console script (skipped otherwise).
    * ``PYTEST_CLOUDSMITH_API_KEY`` and ``PYTEST_CLOUDSMITH_ORGANIZATION``.
    * ``PYTEST_CLOUDSMITH_TERRAFORM_MODULE`` — a module source in a Cloudsmith
      Terraform registry, e.g.
      ``terraform.cloudsmith.io/<org>/<name>/<provider>`` (skipped otherwise).
    * Optionally ``PYTEST_CLOUDSMITH_TERRAFORM_VERSION`` (defaults to a
      wide-open constraint).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap

import pytest

# Authentication-failure fingerprints in `terraform init` output. If none of
# these appear, the helper supplied a credential Terraform accepted.
_AUTH_FAILURE_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "authentication",
    "forbidden",
    "invalid token",
    "could not retrieve",  # Terraform's wording when a creds helper returns nothing
)


def _get_env_var_or_skip(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        pytest.skip(f"{key} not provided")
    return value


@pytest.fixture()
def terraform_bin() -> str:
    """Path to the terraform executable, or skip if it is not installed."""
    path = shutil.which("terraform")
    if not path:
        pytest.skip("terraform is not installed / not on PATH")
    return path


@pytest.fixture()
def helper_bin() -> str:
    """Path to the terraform-credentials-cloudsmith wrapper, or skip."""
    path = shutil.which("terraform-credentials-cloudsmith")
    if not path:
        pytest.skip(
            "terraform-credentials-cloudsmith not on PATH "
            "(install cloudsmith-cli as a console script)"
        )
    return path


@pytest.mark.integration
def test_terraform_init_authenticates_via_helper(
    terraform_bin, helper_bin, tmp_path, monkeypatch
):
    """A `terraform init` with no token on disk authenticates via the helper.

    The test isolates HOME so the developer's real ``~/.terraformrc`` and
    plugin dir are never touched — guaranteeing there is genuinely no token on
    disk and that the *only* credential source is our helper.
    """
    api_key = _get_env_var_or_skip("PYTEST_CLOUDSMITH_API_KEY")
    organization = _get_env_var_or_skip("PYTEST_CLOUDSMITH_ORGANIZATION")
    module_source = _get_env_var_or_skip("PYTEST_CLOUDSMITH_TERRAFORM_MODULE")
    module_version = os.environ.get("PYTEST_CLOUDSMITH_TERRAFORM_VERSION", ">= 0.0.0")

    # --- Isolated, token-free Terraform environment ---------------------------
    fake_home = tmp_path / "home"
    plugin_dir = fake_home / ".terraform.d" / "plugins"
    plugin_dir.mkdir(parents=True)

    # Terraform only searches its default plugin locations for credentials
    # helpers (it ignores -plugin-dir), so drop the wrapper in there.
    helper_link = plugin_dir / "terraform-credentials-cloudsmith"
    try:
        helper_link.symlink_to(helper_bin)
    except OSError:
        shutil.copy2(helper_bin, helper_link)
        helper_link.chmod(0o755)

    # A terraformrc that configures ONLY the helper — deliberately no
    # `credentials` block, so Terraform must consult the helper.
    terraformrc = fake_home / ".terraformrc"
    terraformrc.write_text(
        textwrap.dedent(
            """
            credentials_helper "cloudsmith" {
              args = []
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    # A one-module config: the smallest thing that forces Terraform to
    # authenticate against the Cloudsmith Terraform registry during `init`.
    workdir = tmp_path / "tf"
    workdir.mkdir()
    (workdir / "main.tf").write_text(
        textwrap.dedent(
            f"""
            module "auth_probe" {{
              source  = "{module_source}"
              version = "{module_version}"
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    # Clean, hermetic environment: our fake HOME, our API key for the helper's
    # credential chain, and nothing that could smuggle in a token
    # (TF_TOKEN_*, an inherited ~/.terraformrc, etc.).
    env = {
        "HOME": str(fake_home),
        "PATH": f"{os.path.dirname(helper_bin)}{os.pathsep}{os.environ['PATH']}",
        "CLOUDSMITH_API_KEY": api_key,
        "CLOUDSMITH_ORG": organization,
        # Make Terraform's own credential sources impossible so a pass can only
        # be attributed to the helper.
        "TF_CLI_CONFIG_FILE": str(terraformrc),
        "CHECKPOINT_DISABLE": "1",
        "TF_IN_AUTOMATION": "1",
        "TF_LOG": "trace",  # so the helper invocation is visible on failure
    }
    for key in [k for k in os.environ if k.startswith("TF_TOKEN_")]:
        env[key] = ""  # neutralise any host-specific bearer-token env vars

    result = subprocess.run(
        [terraform_bin, "init", "-no-color", "-input=false"],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    combined = (result.stdout + "\n" + result.stderr).lower()

    # The assertion is specifically about *authentication*, not about whether
    # the module resolved. If init failed, it must not have failed for an
    # auth reason.
    auth_failures = [m for m in _AUTH_FAILURE_MARKERS if m in combined]
    assert not auth_failures, (
        "terraform init failed to authenticate via the credentials helper "
        f"(matched {auth_failures!r}).\n\n"
        f"exit code: {result.returncode}\n\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )
