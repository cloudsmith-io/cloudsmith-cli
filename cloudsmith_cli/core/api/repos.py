"""API - Packages endpoints."""

import cloudsmith_sdk
from cloudsmith_sdk.models import RepositoryCreateRequest, RepositoryRequestPatch

from .. import utils
from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_repos_api() -> cloudsmith_sdk.ReposApi:
    """Get the repos API client."""
    return get_new_api_client().repos


def list_repos(owner=None, **kwargs):
    """List repositories in a namespace."""
    client = get_repos_api()

    api_kwargs = {}
    api_kwargs.update(utils.get_page_kwargs(**kwargs))
    with catch_raise_api_exception():
        if owner:
            repo = kwargs.get("repo", None)
            if repo is not None:
                return [client.read(owner=owner, identifier=repo).to_dict()]

            return client.namespace_list(owner=owner, **api_kwargs)

        return client.user_list(**api_kwargs)


def create_repo(owner, repo_config):
    """Create a repository in a namespace."""
    client = get_repos_api()

    repo_create_request = RepositoryCreateRequest.from_dict(repo_config)

    with catch_raise_api_exception():
        return client.create(owner=owner, body=repo_create_request)


def update_repo(owner, repo, repo_config):
    """Update a repo in a namespace."""
    client = get_repos_api()
    repo_update_request = RepositoryRequestPatch.from_dict(repo_config)

    with catch_raise_api_exception():
        return client.partial_update(
            owner=owner, identifier=repo, body=repo_update_request
        )


def delete_repo(owner, repo):
    """Delete a repo from a namespace."""
    client = get_repos_api()

    with catch_raise_api_exception():
        client.delete(owner=owner, identifier=repo)
