"""API - Packages endpoints."""

import cloudsmith_sdk
from cloudsmith_sdk.models import (
    OrganizationPackageLicensePolicyRequest,
    OrganizationPackageVulnerabilityPolicyRequest,
    PackageDenyPolicyRequest,
)

from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_orgs_api() -> cloudsmith_sdk.OrgsApi:
    """Get the orgs API client."""
    return get_new_api_client().orgs


def list_vulnerability_policies(owner, page_size):
    """List vulnerability policies in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        return client.vulnerability_policy_list(org=owner, page_size=page_size)


def create_vulnerability_policy(owner, policy_config):
    """Create a vulnerability policy in a namespace."""
    client = get_orgs_api()

    vulnerability_policy_request = (
        OrganizationPackageVulnerabilityPolicyRequest.from_dict(policy_config)
    )

    with catch_raise_api_exception():
        return client.vulnerability_policy_create(
            org=owner, body=vulnerability_policy_request
        )


def update_vulnerability_policy(owner, slug_perm, policy_config):
    """Update a vulnerability policy in a namespace."""
    client = get_orgs_api()

    vulnerability_policy_request = (
        OrganizationPackageVulnerabilityPolicyRequest.from_dict(policy_config)
    )

    with catch_raise_api_exception():
        return client.vulnerability_policy_partial_update(
            org=owner, slug_perm=slug_perm, body=vulnerability_policy_request
        )


def delete_vulnerability_policy(owner, slug_perm):
    """Delete a vulnerability_policy from a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        client.vulnerability_policy_delete(org=owner, slug_perm=slug_perm)


def list_license_policies(owner, page, page_size):
    """List license policies in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        return client.license_policy_list(org=owner, page_size=page_size)


def create_license_policy(owner, policy_config):
    """Create a license policy in a namespace."""
    client = get_orgs_api()

    license_policy_request = OrganizationPackageLicensePolicyRequest.from_dict(
        policy_config
    )

    with catch_raise_api_exception():
        return client.license_policy_create(org=owner, body=license_policy_request)


def update_license_policy(owner, slug_perm, policy_config):
    """Update a license policy in a namespace."""
    client = get_orgs_api()

    license_policy_request = OrganizationPackageLicensePolicyRequest.from_dict(
        policy_config
    )

    with catch_raise_api_exception():
        return client.license_policy_partial_update(
            org=owner, slug_perm=slug_perm, body=license_policy_request
        )


def delete_license_policy(owner, slug_perm):
    """Delete a license policy from a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        client.license_policy_delete(org=owner, slug_perm=slug_perm)


def list_deny_policies(owner, page, page_size):
    """List deny policies in a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        return client.deny_policy_list(org=owner, page_size=page_size)


def create_deny_policy(owner, policy_config):
    """Create a deny policy in a namespace."""
    client = get_orgs_api()

    deny_policy_request = PackageDenyPolicyRequest.from_dict(policy_config)

    with catch_raise_api_exception():
        return client.deny_policy_create(org=owner, body=deny_policy_request)


def get_deny_policy(owner, slug_perm):
    """Get a deny policy from a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        return client.deny_policy_read(org=owner, slug_perm=slug_perm)


def update_deny_policy(owner, slug_perm, policy_config):
    """Update a deny policy in a namespace."""
    client = get_orgs_api()

    deny_policy_request = PackageDenyPolicyRequest.from_dict(policy_config)

    with catch_raise_api_exception():
        return client.deny_policy_partial_update(
            org=owner, slug_perm=slug_perm, body=deny_policy_request
        )


def delete_deny_policy(owner, slug_perm):
    """Delete a deny policy from a namespace."""
    client = get_orgs_api()

    with catch_raise_api_exception():
        client.deny_policy_delete(org=owner, slug_perm=slug_perm)
