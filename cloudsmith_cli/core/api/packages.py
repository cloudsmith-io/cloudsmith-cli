"""API - Packages endpoints."""

import dataclasses
import inspect

import cloudsmith_sdk
import cloudsmith_sdk.models._v1 as _v1_models
from cloudsmith_sdk.models import (
    PackageCopyRequest,
    PackageMoveRequest,
    PackageQuarantineRequest,
    PackageTagRequest,
)

from .. import utils
from .exceptions import catch_raise_api_exception
from .init import get_new_api_client


def get_packages_api() -> cloudsmith_sdk.PackagesApi:
    """Get the packages API client."""
    return get_new_api_client().packages


def make_create_payload(**kwargs):
    """Create payload for upload/check-upload operations."""
    payload = {}
    # Add non-empty arguments
    for k, v in kwargs.items():
        if v is not None:
            payload[k] = v

    return payload


def create_package(package_format, owner, repo, **kwargs):
    """Create a new package in a repository."""
    client = get_packages_api()

    with catch_raise_api_exception():
        upload = getattr(client, "upload_%s" % package_format)

        data = upload(owner=owner, repo=repo, body=make_create_payload(**kwargs))

    return data.slug_perm, data.slug


def validate_create_package(package_format, owner, repo, **kwargs):
    """Validate parameters for creating a package."""
    client = get_packages_api()

    with catch_raise_api_exception():
        check = getattr(client, "validate_upload_%s" % package_format)

        check(owner=owner, repo=repo, body=make_create_payload(**kwargs))

    return True


def copy_package(owner, repo, identifier, destination):
    """Copy a package to another repository."""
    client = get_packages_api()

    package_copy_request = PackageCopyRequest(destination=destination)

    with catch_raise_api_exception():
        data = client.copy(
            owner=owner,
            repo=repo,
            identifier=identifier,
            body=package_copy_request,
        )

    return data.slug_perm, data.slug


def move_package(owner, repo, identifier, destination):
    """Move a package to another repository."""
    client = get_packages_api()

    package_move_request = PackageMoveRequest(destination=destination)

    with catch_raise_api_exception():
        data = client.move(
            owner=owner,
            repo=repo,
            identifier=identifier,
            body=package_move_request,
        )

    return data.slug_perm, data.slug


def delete_package(owner, repo, identifier):
    """Delete a package in a repository."""
    client = get_packages_api()

    with catch_raise_api_exception():
        client.delete(owner=owner, repo=repo, identifier=identifier)

    return True


def resync_package(owner, repo, identifier):
    """Resync a package in a repository."""
    client = get_packages_api()

    with catch_raise_api_exception():
        data = client.resync(owner=owner, repo=repo, identifier=identifier)

    return data.slug_perm, data.slug


def quarantine_package(owner, repo, identifier):
    """Quarantine a package."""
    client = get_packages_api()

    with catch_raise_api_exception():
        data = client.quarantine(owner=owner, repo=repo, identifier=identifier)

    return data.slug_perm, data.slug


def quarantine_restore_package(owner, repo, identifier):
    """Restorea a package from quarantine."""
    client = get_packages_api()

    with catch_raise_api_exception():
        data = client.quarantine(
            owner=owner,
            repo=repo,
            identifier=identifier,
            body=PackageQuarantineRequest(restore=True),
        )

    return data.slug_perm, data.slug


def tag_package(owner, repo, identifier, data):
    """Manage tags for a package in a repository."""
    client = get_packages_api()

    package_tag_request = PackageTagRequest.from_dict(data)

    with catch_raise_api_exception():
        data = client.tag(
            owner=owner, repo=repo, identifier=identifier, body=package_tag_request
        )

    return data.tags, data.tags_immutable


def get_package_status(owner, repo, identifier):
    """Get the status for a package in a repository."""
    client = get_packages_api()

    with catch_raise_api_exception():
        data = client.status(owner=owner, repo=repo, identifier=identifier)

    # pylint: disable=no-member
    # Pylint detects the returned value as a tuple
    return (
        data.is_sync_completed,
        data.is_sync_failed,
        data.sync_progress,
        data.status_str,
        data.stage_str,
        data.status_reason,
    )


def get_package_dependencies(owner, repo, identifier):
    """Get the direct dependencies for a package in a repository."""
    client = get_packages_api()

    with catch_raise_api_exception():
        data = client.dependencies(owner=owner, repo=repo, identifier=identifier)

    return data.dependencies


def get_package_tags(owner, repo, identifier):
    """Get the tags for a package in a repository."""
    client = get_packages_api()

    with catch_raise_api_exception():
        data = client.read(owner=owner, repo=repo, identifier=identifier)

    # pylint: disable=no-member
    # Pylint detects the returned value as a tuple
    return (data.tags, data.tags_immutable)


def list_packages(owner, repo, **kwargs):
    """List packages for a repository."""
    client = get_packages_api()

    api_kwargs = {}
    api_kwargs.update(utils.get_page_kwargs(**kwargs))
    api_kwargs.update(utils.get_query_kwargs(**kwargs))
    api_kwargs.update(utils.get_sort_kwargs(**kwargs))

    with catch_raise_api_exception():
        return client.list(owner=owner, repo=repo, **api_kwargs)


_PARAMETER_HELP = {
    "architecture": "Binary package uploads for macOS should specify the architecture they were built for.",
    "artifact_id": "The ID of the artifact.",
    "author_name": "The name of the author of the package.",
    "author_org": "The organization of the author.",
    "changes_file": "The changes archive containing the changes made to the source and debian packaging files",
    "component": "The component (channel) for the package (e.g. 'main', 'unstable', etc.)",
    "conan_channel": "Conan channel.",
    "conan_prefix": "Conan prefix (User).",
    "content_type": "A custom content/media (also known as MIME) type to be sent when downloading this file. By default Cloudsmith will attempt to detect the type, but if you need to override it, you can specify it here.",
    "description": "A textual description of this package.",
    "distribution": "The distribution to store the package for.",
    "extra_files": "Extra files to include in the package. This can be a single file or multiple files.",
    "filepath": "The full filepath of the package including filename.",
    "group_id": "Artifact's group ID.",
    "info_file": "The info file is an python file containing the package metadata.",
    "ivy_file": "The ivy file is an XML file describing the dependencies of the project.",
    "javadoc_file": "Adds bundled Java documentation to the Maven package",
    "license_url": "The license URL of this package.",
    "manifest_file": "The info file is an python file containing the package metadata.",
    "metadata_file": "The conan file is an python file containing the package metadata.",
    "name": "The name of this package.",
    "npm_dist_tag": "The default npm dist-tag for this package/version - This will replace any other package/version if they are using the same tag.",
    "package_file": "The primary file for the package.",
    "packaging": "Artifact's Maven packaging type.",
    "pom_file": "The POM file is an XML file containing the Maven coordinates.",
    "provenance_file": "The provenance file containing the signature for the chart. If one is not provided, it will be generated automatically.",
    "provider": "The virtual machine provider for the box.",
    "r_version": "Binary package uploads should specify the version of R they were built for.",
    "readme_url": "The URL of the readme for the package.",
    "repository_url": "The URL of the SCM repository for the package.",
    "republish": "If true, the uploaded package will overwrite any others with the same attributes (e.g. same version); otherwise, it will be flagged as a duplicate.",
    "sbt_version": ":return: The sbt_version of this MavenPackageUploadRequest.",
    "scala_version": ":return: The scala_version of this MavenPackageUploadRequest.",
    "scope": "A scope provides a namespace for related packages within the package registry.",
    "sources_file": "The sources archive containing the source code for the binary",
    "summary": "A one-liner synopsis of this package.",
    "symbols_file": "Uploads a symbols file as a separate package",
    "tags": "A comma-separated values list of tags to add to the package.",
    "tests_file": "Adds bundled Java tests to the Maven package.",
    "version": "The raw version for this package.",
}

_REQUIRED_OVERRIDES = {
    "alpine": {"distribution", "package_file"},
    "conan": {"info_file", "manifest_file", "metadata_file", "package_file"},
    "deb": {"distribution", "package_file"},
    "generic": {"filepath", "package_file"},
    "maven": {"package_file"},
    "rpm": {"distribution", "package_file"},
    "swift": {"name", "package_file", "scope", "version"},
    "vagrant": {"name", "package_file", "provider", "version"},
}

_HELP_OVERRIDES = {
    "maven": {
        "sources_file": "Adds bundled Java source code to the Maven package.",
    },
}

_DEFAULT_REQUIRED = {"package_file"}


def get_package_formats():
    """Get the list of available package formats and parameters."""
    formats = {}

    for name, cls in inspect.getmembers(_v1_models, dataclasses.is_dataclass):
        if not name.endswith("PackageUploadRequest"):
            continue

        fmt = name.replace("PackageUploadRequest", "").lower()
        required_fields = _REQUIRED_OVERRIDES.get(fmt, _DEFAULT_REQUIRED)
        help_overrides = _HELP_OVERRIDES.get(fmt, {})

        params = {}
        for field in dataclasses.fields(cls):
            if "bool" in field.type:
                cli_type = "bool"
            else:
                cli_type = "str"

            help_text = help_overrides.get(
                field.name, _PARAMETER_HELP.get(field.name, "")
            )

            params[field.name] = {
                "type": cli_type,
                "help": help_text,
                "required": field.name in required_fields,
            }

        formats[fmt] = params

    return formats


def get_package_format_names(predicate=None):
    """Get names for available package formats."""
    return [
        k for k, v in get_package_formats().items() if not predicate or predicate(k, v)
    ]


def get_package_format_names_with_distros():
    """Get names for package formats that support distributions."""
    return get_package_format_names(lambda k, v: "distribution" in v)
