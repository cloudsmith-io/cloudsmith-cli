"""API - Packages endpoints."""

import cloudsmith_api

from .. import ratelimits, utils
from ..pagination import PageInfo
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_repos_api():
    """Get the repos API client."""
    return get_api_client(cloudsmith_api.ReposApi)


def list_repos(owner=None, **kwargs):
    """List repositories in a namespace."""
    client = get_repos_api()

    api_kwargs = {}
    api_kwargs.update(utils.get_page_kwargs(**kwargs))

    if owner:
        repo = kwargs.get("repo", None)
        if repo is not None:
            if hasattr(client, "repos_read_with_http_info"):
                with catch_raise_api_exception():
                    res, _, headers = client.repos_read_with_http_info(owner, repo)
                    res = [res]
        else:
            api_kwargs["owner"] = owner

            if hasattr(client, "repos_namespace_list_with_http_info"):
                with catch_raise_api_exception():
                    res, _, headers = client.repos_namespace_list_with_http_info(
                        **api_kwargs
                    )
    else:
        if hasattr(client, "repos_user_list_with_http_info"):
            with catch_raise_api_exception():
                res, _, headers = client.repos_user_list_with_http_info(**api_kwargs)

    ratelimits.maybe_rate_limit(client, headers)
    page_info = PageInfo.from_headers(headers)
    return [x.to_dict() for x in res], page_info


def create_repo(owner, repo_config):
    """Create a repository in a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_create_with_http_info(
            owner=owner, data=repo_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def update_repo(owner, repo, repo_config):
    """Update a repo in a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_partial_update_with_http_info(
            owner, repo, data=repo_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def delete_repo(owner, repo):
    """Delete a repo from a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        _, _, headers = client.repos_delete_with_http_info(owner, repo)

    ratelimits.maybe_rate_limit(client, headers)


def list_repo_gpg_key(owner, repo):
    """Get the active GPG key for a repository."""
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_gpg_list_with_http_info(owner, repo)

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def create_repo_gpg_key(owner, repo, gpg_private_key, gpg_passphrase=None):
    """Set (upload) the active GPG key for a repository."""
    client = get_repos_api()

    gpg_key_create = cloudsmith_api.RepositoryGpgKeyCreate(
        gpg_private_key=gpg_private_key, gpg_passphrase=gpg_passphrase
    )

    with catch_raise_api_exception():
        data, _, headers = client.repos_gpg_create_with_http_info(
            owner, repo, data=gpg_key_create
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def regenerate_repo_gpg_key(owner, repo):
    """Regenerate the GPG key for a repository."""
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_gpg_regenerate_with_http_info(owner, repo)

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def list_repo_privileges(owner, repo):
    """Get the explicit team/user/service privileges on a repository.

    The endpoint returns every privilege in a single response and ignores
    page parameters, so there is nothing to paginate over here.
    """
    client = get_repos_api()

    with catch_raise_api_exception():
        data, _, headers = client.repos_privileges_list_with_http_info(owner, repo)

    ratelimits.maybe_rate_limit(client, headers)
    return [privilege.to_dict() for privilege in data.privileges]


def update_repo_privileges(owner, repo, privileges):
    """Add or raise one or more explicit privileges on a repository.

    ``privileges`` is a list of dicts, each shaped like
    ``{"privilege": "Read"|"Write"|"Admin", "team": <slug>}`` (or ``"user"``
    or ``"service"`` in place of ``"team"``). This calls the
    ``PATCH .../privileges`` endpoint, which the API documents (and manual
    verification against a live org confirmed) as an upsert: each entry is
    matched against the repository's existing privileges by its
    team/user/service key and updated in place, or added if no match exists.
    Entries not mentioned are left untouched, so callers don't need to read
    the existing list first.
    """
    client = get_repos_api()

    with catch_raise_api_exception():
        _, _, headers = client.repos_privileges_partial_update_with_http_info(
            owner, repo, data={"privileges": privileges}
        )

    ratelimits.maybe_rate_limit(client, headers)


def replace_repo_privileges(owner, repo, privileges):
    """Replace every explicit privilege on a repository with ``privileges``.

    This calls the ``PUT .../privileges`` endpoint, which is a whole-list
    write: anything absent from ``privileges`` loses its explicit access.
    The API has no way to delete a single privilege, so revoking is also
    expressed as a replace of the entries being kept.
    """
    client = get_repos_api()

    with catch_raise_api_exception():
        _, _, headers = client.repos_privileges_update_with_http_info(
            owner, repo, data={"privileges": privileges}
        )

    ratelimits.maybe_rate_limit(client, headers)
