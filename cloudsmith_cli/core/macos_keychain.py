"""In-place updates for macOS keychain items.

The keyring library implements each write as a delete followed by a
re-create (see set_generic_password in keyring/backends/macOS/api.py,
https://github.com/jaraco/keyring). macOS attaches the access control
list to the item, so the re-created item forgets every access grant
the user approved and the keychain prompts return on the next read.
SecItemUpdate changes the stored secret on the existing item and
keeps the access control list intact.

The built-in backend cannot give this behavior: set_password is
hard-coded to delete and re-create, the backend exposes no update
function, and no configuration option changes the write path.
keyring 25.7.0, current at the time of this change, contains no fix.
The upstream reports https://github.com/jaraco/keyring/issues/619
and https://github.com/jaraco/keyring/issues/512 describe the
resulting prompt storm but not the access control list reset that
causes it, so this module binds SecItemUpdate itself.

This module does not register a keyring backend, and the backend
discovery is unchanged. cloudsmith_cli.core.keyring tries
update_generic_password before each write and falls back to the
normal keyring write when the item does not exist or the update
fails.

The Security and CoreFoundation bindings load on the first call, not
at import time, so the module imports cleanly on every platform.

The kSec* constants mirror the attributes that the keyring backend
stores, so an update targets exactly the items that keyring creates
and reads:

- kSecClass with kSecClassGenericPassword selects the item class.
- kSecAttrService and kSecAttrAccount identify one item; keyring
  stores its service name and username in them.
- kSecValueData holds the secret payload.

See "Searching for keychain items":
https://developer.apple.com/documentation/security/keychain_services/keychain_items/searching_for_keychain_items
and SecItemUpdate:
https://developer.apple.com/documentation/security/1393617-secitemupdate
"""

import ctypes
import functools
from ctypes import c_int32, c_void_p
from ctypes.util import find_library
from types import SimpleNamespace

_KCF_STRING_ENCODING_UTF8 = 0x08000100
_ERR_SEC_SUCCESS = 0


@functools.cache
def _get_bindings():
    security = ctypes.CDLL(find_library("Security"))
    core_foundation = ctypes.CDLL(find_library("CoreFoundation"))

    cf_string_create = core_foundation.CFStringCreateWithCString
    cf_string_create.restype = c_void_p
    cf_string_create.argtypes = (c_void_p, ctypes.c_char_p, ctypes.c_uint32)

    cf_data_create = core_foundation.CFDataCreate
    cf_data_create.restype = c_void_p
    cf_data_create.argtypes = (c_void_p, ctypes.c_char_p, ctypes.c_long)

    cf_dictionary_create = core_foundation.CFDictionaryCreate
    cf_dictionary_create.restype = c_void_p
    cf_dictionary_create.argtypes = (
        c_void_p,
        c_void_p,
        c_void_p,
        ctypes.c_long,
        c_void_p,
        c_void_p,
    )

    cf_release = core_foundation.CFRelease
    cf_release.restype = None
    cf_release.argtypes = (c_void_p,)

    sec_item_update = security.SecItemUpdate
    sec_item_update.restype = c_int32
    sec_item_update.argtypes = (c_void_p, c_void_p)

    return SimpleNamespace(
        security=security,
        cf_string_create=cf_string_create,
        cf_data_create=cf_data_create,
        cf_dictionary_create=cf_dictionary_create,
        cf_release=cf_release,
        sec_item_update=sec_item_update,
        dictionary_key_callbacks=core_foundation.kCFTypeDictionaryKeyCallBacks,
        dictionary_value_callbacks=core_foundation.kCFTypeDictionaryValueCallBacks,
    )


def _security_constant(bindings, name):
    return c_void_p.in_dll(bindings.security, name)


def _cf_string(bindings, value):
    return bindings.cf_string_create(
        None, value.encode("utf-8"), _KCF_STRING_ENCODING_UTF8
    )


def _cf_dictionary(bindings, pairs):
    keys = (c_void_p * len(pairs))(*(key for key, _ in pairs))
    values = (c_void_p * len(pairs))(*(value for _, value in pairs))
    return bindings.cf_dictionary_create(
        None,
        keys,
        values,
        len(pairs),
        bindings.dictionary_key_callbacks,
        bindings.dictionary_value_callbacks,
    )


def _release(bindings, refs):
    for ref in refs:
        if ref:
            bindings.cf_release(ref)


def update_generic_password(service, account, value):
    """Update an existing generic password item in place.

    SecItemUpdate takes two dictionaries: a query that identifies the
    item (class, service, account) and the attributes to change (the
    secret data). Return True when the update succeeds. Return False
    when the item does not exist, when macOS rejects the update, or
    when the Security framework is not available.
    """
    try:
        bindings = _get_bindings()
        class_key = _security_constant(bindings, "kSecClass")
        class_value = _security_constant(bindings, "kSecClassGenericPassword")
        service_key = _security_constant(bindings, "kSecAttrService")
        account_key = _security_constant(bindings, "kSecAttrAccount")
        value_key = _security_constant(bindings, "kSecValueData")
    except (OSError, AttributeError, ValueError):
        return False
    encoded_value = value.encode("utf-8")
    service_ref = _cf_string(bindings, service)
    account_ref = _cf_string(bindings, account)
    value_ref = bindings.cf_data_create(None, encoded_value, len(encoded_value))
    query = None
    attributes = None
    try:
        if not (service_ref and account_ref and value_ref):
            return False
        query = _cf_dictionary(
            bindings,
            [
                (class_key, class_value),
                (service_key, service_ref),
                (account_key, account_ref),
            ],
        )
        attributes = _cf_dictionary(bindings, [(value_key, value_ref)])
        if not (query and attributes):
            return False
        status = bindings.sec_item_update(query, attributes)
        return status == _ERR_SEC_SUCCESS
    finally:
        _release(bindings, (query, attributes, service_ref, account_ref, value_ref))
