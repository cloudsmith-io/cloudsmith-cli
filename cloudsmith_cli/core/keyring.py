import getpass
import os
import sys
from datetime import datetime, timedelta, timezone

ACCESS_TOKEN_KEY = "cloudsmith_cli-access_token-{api_host}"


def should_use_keyring():
    """Check if keyring should be used based on CLOUDSMITH_NO_KEYRING env var."""
    env_value = os.environ.get("CLOUDSMITH_NO_KEYRING", "").strip().lower()
    return env_value not in ("1", "true", "yes")


ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY = (
    "cloudsmith_cli-access_token_refresh_attempted_at-{api_host}"
)
REFRESH_TOKEN_KEY = "cloudsmith_cli-refresh_token-{api_host}"


def _get_username():
    return getpass.getuser()


def _is_scoped_profile(profile):
    return bool(profile) and profile != "default"


def _format_key(template, api_host, profile):
    key = template.format(api_host=api_host)
    if _is_scoped_profile(profile):
        return f"{key}-profile-{profile}"
    return key


def _get_value_with_fallback(template, api_host, profile):
    """Read the profile-scoped entry, with fallback to the legacy entry.

    Tokens stored before profile scoping existed live in unscoped
    entries. The fallback keeps those sessions valid. Writes go to the
    scoped entry, so the tokens migrate on the next refresh.
    """
    value = _get_value(_format_key(template, api_host, profile))
    if value is None and _is_scoped_profile(profile):
        value = _get_value(_format_key(template, api_host, None))
    return value


def _sync_keyring_backend_env():
    """Allow CLOUDSMITH_KEYRING_BACKEND to alias PYTHON_KEYRING_BACKEND."""
    alias_value = os.environ.get("CLOUDSMITH_KEYRING_BACKEND")
    if alias_value and "PYTHON_KEYRING_BACKEND" not in os.environ:
        os.environ["PYTHON_KEYRING_BACKEND"] = alias_value


def _sync_keyring_property_env():
    """Allow CLOUDSMITH_KEYRING_KEY to alias KEYRING_PROPERTY_KEYRING_KEY."""
    alias_value = os.environ.get("CLOUDSMITH_KEYRING_KEY")
    if alias_value and "KEYRING_PROPERTY_KEYRING_KEY" not in os.environ:
        os.environ["KEYRING_PROPERTY_KEYRING_KEY"] = alias_value


def _expand_path(value):
    return os.path.expanduser(os.path.expandvars(value))


def _sync_keyring_file_path_env():
    """Allow CLOUDSMITH_KEYRING_FILE_PATH to alias KEYRING_PROPERTY_FILE_PATH."""
    alias_value = os.environ.get("CLOUDSMITH_KEYRING_FILE_PATH")
    if alias_value and "KEYRING_PROPERTY_FILE_PATH" not in os.environ:
        os.environ["KEYRING_PROPERTY_FILE_PATH"] = _expand_path(alias_value)


def _apply_keyring_file_location(backend):
    """Set the storage file location before other properties apply.

    The cryptfile keyring_key setter opens the storage file at
    assignment time. Set the file location first, so the backend opens
    the correct file. A file path env var takes precedence over
    CLOUDSMITH_KEYRING_DIR. With the directory, the backend keeps its
    default filename. The function ignores backends without a storage
    file.
    """
    file_path = os.environ.get("KEYRING_PROPERTY_FILE_PATH")
    if file_path:
        backend.file_path = file_path
        return
    dir_value = os.environ.get("CLOUDSMITH_KEYRING_DIR")
    if not dir_value:
        return
    filename = getattr(backend, "filename", None)
    if not filename:
        return
    backend.file_path = os.path.join(_expand_path(dir_value), filename)


def _prepare_keyring_backend():
    """Resolve env var aliases and apply them to the keyring backend.

    keyrings.cryptfile and keyrings.alt override KeyringBackend.__init__
    without calling super(), so KEYRING_PROPERTY_* env vars (e.g. the
    keyring_key password for those encrypted file backends) never reach
    them through the library's own documented mechanism. Apply them here
    instead, once the backend has been resolved.
    """
    import keyring

    _sync_keyring_backend_env()
    _sync_keyring_property_env()
    _sync_keyring_file_path_env()
    backend = keyring.get_keyring()
    _apply_keyring_file_location(backend)
    backend.set_properties_from_env()


def _get_value(key):
    import keyring
    from keyring.errors import KeyringError

    _prepare_keyring_backend()
    username = _get_username()
    try:
        return keyring.get_password(key, username)
    except KeyringError:
        return None


def _import_macos_keychain():
    try:
        from . import macos_keychain
    except (OSError, AttributeError):
        return None
    return macos_keychain


def _effective_backend():
    import keyring

    backend = keyring.get_keyring()
    chained_backends = getattr(backend, "backends", None)
    if chained_backends:
        return chained_backends[0]
    return backend


def _update_keychain_item_in_place(service, username, value):
    """Update the item with SecItemUpdate to keep its access control list.

    keyring deletes and re-creates the item on write. That resets the
    access control list that the user approved in the keychain prompt.
    """
    if sys.platform != "darwin":
        return False
    backend_module = type(_effective_backend()).__module__
    if not backend_module.startswith("keyring.backends.macOS"):
        return False
    keychain = _import_macos_keychain()
    if keychain is None:
        return False
    return keychain.update_generic_password(service, username, value)


def _set_value(key, value):
    import keyring

    _prepare_keyring_backend()
    username = _get_username()
    if _update_keychain_item_in_place(key, username, value):
        return
    keyring.set_password(key, username, value)


def store_access_token(api_host, access_token, profile=None):
    key = _format_key(ACCESS_TOKEN_KEY, api_host, profile)
    _set_value(key, access_token)


def get_access_token(api_host, profile=None):
    if not should_use_keyring():
        return None
    return _get_value_with_fallback(ACCESS_TOKEN_KEY, api_host, profile)


def update_refresh_attempted_at(api_host, refresh_time=None, profile=None):
    if refresh_time is None:
        refresh_time = datetime.now(tz=timezone.utc)

    refresh_attempted_at_value = refresh_time.isoformat()

    key = _format_key(ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY, api_host, profile)
    _set_value(key, refresh_attempted_at_value)


def get_refresh_attempted_at(api_host, profile=None):
    value = _get_value_with_fallback(
        ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY, api_host, profile
    )

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def should_refresh_access_token(api_host, profile=None):
    if not should_use_keyring():
        return False

    token_refreshed_at = get_refresh_attempted_at(api_host, profile=profile)

    if token_refreshed_at:
        return token_refreshed_at < (
            datetime.now(tz=timezone.utc) - timedelta(minutes=30)
        )

    return True


def store_refresh_token(api_host, refresh_token, profile=None):
    key = _format_key(REFRESH_TOKEN_KEY, api_host, profile)
    _set_value(key, refresh_token)


def get_refresh_token(api_host, profile=None):
    return _get_value_with_fallback(REFRESH_TOKEN_KEY, api_host, profile)


def store_sso_tokens(api_host, access_token, refresh_token, profile=None):
    """Store SSO tokens in keyring if enabled."""
    if not should_use_keyring():
        return False

    if access_token:
        store_access_token(
            api_host=api_host, access_token=access_token, profile=profile
        )
        update_refresh_attempted_at(api_host=api_host, profile=profile)

    if refresh_token:
        store_refresh_token(
            api_host=api_host, refresh_token=refresh_token, profile=profile
        )

    return True


def _delete_value(key):
    import keyring
    from keyring.errors import KeyringError

    _prepare_keyring_backend()
    username = _get_username()
    try:
        keyring.delete_password(key, username)
        return True
    except KeyringError:
        return False


def _sso_keys(api_host, profile=None, include_legacy=True):
    """Return the keyring service names for all SSO-related entries.

    For a scoped profile with include_legacy, the list also contains the
    legacy unscoped entries so that the caller removes pre-scoping
    sessions.
    """
    templates = [
        ACCESS_TOKEN_KEY,
        REFRESH_TOKEN_KEY,
        ACCESS_TOKEN_REFRESH_ATTEMPTED_AT_KEY,
    ]
    keys = [_format_key(template, api_host, profile) for template in templates]
    if include_legacy and _is_scoped_profile(profile):
        keys += [_format_key(template, api_host, None) for template in templates]
    return keys


def has_sso_tokens(api_host, profile=None):
    """Check if any SSO tokens exist in the keyring for the given host."""
    if not should_use_keyring():
        return False
    return any(_get_value(key) for key in _sso_keys(api_host, profile=profile))


def delete_sso_tokens(api_host, profile=None, include_legacy=True):
    """Delete all SSO tokens from the keyring for the given host.

    Set include_legacy to False to keep the legacy unscoped entries,
    which hold the default profile's session.
    """
    keys = _sso_keys(api_host, profile=profile, include_legacy=include_legacy)
    results = [_delete_value(key) for key in keys]
    return any(results)


OIDC_TOKEN_KEY = "cloudsmith_cli-oidc_token-{api_host}-{org}-{service_slug}"


def store_oidc_token(api_host, org, service_slug, token_data):
    """Store OIDC token in keyring if enabled."""
    from keyring.errors import KeyringError

    if not should_use_keyring():
        return False

    key = OIDC_TOKEN_KEY.format(api_host=api_host, org=org, service_slug=service_slug)
    try:
        _set_value(key, token_data)
        return True
    except KeyringError:
        return False


def get_oidc_token(api_host, org, service_slug):
    """Retrieve OIDC token from keyring."""
    if not should_use_keyring():
        return None

    key = OIDC_TOKEN_KEY.format(api_host=api_host, org=org, service_slug=service_slug)
    return _get_value(key)


def delete_oidc_token(api_host, org, service_slug):
    """Delete OIDC token from keyring."""
    key = OIDC_TOKEN_KEY.format(api_host=api_host, org=org, service_slug=service_slug)
    return _delete_value(key)
