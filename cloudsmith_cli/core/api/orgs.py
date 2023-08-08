"""API - Packages endpoints."""

import cloudsmith_api

from .. import ratelimits
from ..pagination import PageInfo
from .exceptions import catch_raise_api_exception
from .init import get_api_client


def get_orgs_api():
    """Get the orgs API client."""
    return get_api_client(cloudsmith_api.OrgsApi)


def list_vulnerability_policies(owner, page, page_size):
    """List vulnerability policies in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        policies, _, headers = client.orgs_vulnerability_policy_list_with_http_info(
            org=owner, page=page, page_size=page_size
        )

    ratelimits.maybe_rate_limit(client, headers)
    page_info = PageInfo.from_headers(headers)
    return [policy.to_dict() for policy in policies], page_info


def create_vulnerability_policy(owner, policy_config):
    """Create a vulnerability policy in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        policy, _, headers = client.orgs_vulnerability_policy_create_with_http_info(
            org=owner, data=policy_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return policy.to_dict()


def update_vulnerability_policy(owner, slug_perm, policy_config):
    """Update a vulnerability policy in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        (
            data,
            _,
            headers,
        ) = client.orgs_vulnerability_policy_partial_update_with_http_info(
            owner, slug_perm, data=policy_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return data.to_dict()


def delete_vulnerability_policy(owner, slug_perm):
    """Delete a vulnerability_policy from a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        _, _, headers = client.orgs_vulnerability_policy_delete_with_http_info(
            owner, slug_perm
        )

    ratelimits.maybe_rate_limit(client, headers)


def list_license_policies(owner, page, page_size):
    """List license policies in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        policies, _, headers = client.orgs_license_policy_list_with_http_info(
            org=owner, page=page, page_size=page_size
        )

    ratelimits.maybe_rate_limit(client, headers)
    page_info = PageInfo.from_headers(headers)
    return [policy.to_dict() for policy in policies], page_info


def create_license_policy(owner, policy_config):
    """Create a license policy in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        policy, _, headers = client.orgs_license_policy_create_with_http_info(
            org=owner, data=policy_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return policy.to_dict()


def update_license_policy(owner, slug_perm, policy_config):
    """Update a license policy in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        policy, _, headers = client.orgs_license_policy_partial_update_with_http_info(
            org=owner, slug_perm=slug_perm, data=policy_config
        )

    ratelimits.maybe_rate_limit(client, headers)
    return policy.to_dict()


def delete_license_policy(owner, slug_perm):
    """Delete a license policy from a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        _, _, headers = client.orgs_license_policy_delete_with_http_info(
            owner, slug_perm
        )

    ratelimits.maybe_rate_limit(client, headers)
