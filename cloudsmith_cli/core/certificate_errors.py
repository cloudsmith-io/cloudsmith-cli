# Copyright 2026 Cloudsmith Ltd
"""Explain TLS certificate verification failures."""

from typing import NamedTuple

#: OpenSSL gives these verify codes only when VERIFY_X509_STRICT is on
#: (X509_V_ERR_SIGNATURE_ALGORITHM_INCONSISTENCY, and
#: X509_V_ERR_PATHLEN_INVALID_FOR_NON_CA to X509_V_ERR_EC_KEY_EXPLICIT_PARAMS).
STRICT_ONLY_VERIFY_CODES = frozenset({78, *range(80, 95)})

#: Verify codes for a certificate chain that does not end at a trusted CA.
UNTRUSTED_CA_VERIFY_CODES = frozenset({2, 18, 19, 20, 21})


def find_certificate_error(exc):
    """Return the ``ssl.SSLCertVerificationError`` behind ``exc``, or None."""
    import ssl

    pending = [exc]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return current
        linked = (
            current.__cause__,
            current.__context__,
            getattr(current, "reason", None),
            *current.args,
        )
        pending.extend(item for item in linked if isinstance(item, BaseException))
    return None


class CertificateFailure(NamedTuple):
    """A certificate verification failure, in the parts of a five-part error."""

    code: str
    description: str
    fix: str | None = None


def classify_certificate_error(exc):
    """Return the ``CertificateFailure`` behind ``exc``, or None."""
    error = find_certificate_error(exc)
    if error is None:
        return None

    verify_code = getattr(error, "verify_code", None)
    reason = (getattr(error, "verify_message", None) or str(error)).rstrip(".")
    if verify_code in STRICT_ONLY_VERIFY_CODES:
        return CertificateFailure(
            "E_TLS_STRICT",
            f"The TLS certificate failed a strict X.509 check: {reason}. "
            "Python 3.13 and later apply these checks, and certificates from "
            "TLS-intercepting proxies often fail them.",
            "To turn off only the strict checks, use --without-ssl-verify-strict "
            "or set CLOUDSMITH_SSL_VERIFY_STRICT=0.",
        )
    if verify_code in UNTRUSTED_CA_VERIFY_CODES:
        return CertificateFailure(
            "E_TLS_UNTRUSTED_CA",
            f"The TLS certificate is not from a trusted CA: {reason}.",
            "If your network uses a TLS-intercepting proxy, set REQUESTS_CA_BUNDLE "
            "to a CA bundle that contains the proxy CA.",
        )
    return CertificateFailure(
        "E_TLS_INVALID", f"The TLS certificate is not valid: {reason}."
    )


def describe_certificate_error(exc):
    """Explain the certificate verification failure behind ``exc``, or return None."""
    failure = classify_certificate_error(exc)
    if failure is None:
        return None
    return " ".join(part for part in (failure.description, failure.fix) if part)
