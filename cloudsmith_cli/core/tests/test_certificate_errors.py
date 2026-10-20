import ssl

import requests
from urllib3.exceptions import MaxRetryError, SSLError

from ..certificate_errors import describe_certificate_error


def certificate_error(verify_code, verify_message):
    """Build the exception chain that requests raises for a failed handshake."""
    error = ssl.SSLCertVerificationError(
        1, f"certificate verify failed: {verify_message}"
    )
    error.verify_code = verify_code
    error.verify_message = verify_message
    return requests.exceptions.SSLError(MaxRetryError(None, "/", SSLError(error)))


class TestDescribeCertificateError:
    def test_strict_only_failure_names_the_opt_out(self):
        hint = describe_certificate_error(
            certificate_error(
                78, "cert info signature and signature algorithm mismatch"
            )
        )

        assert (
            "strict X.509 check: cert info signature and signature algorithm mismatch"
            in hint
        )
        assert "--without-ssl-verify-strict" in hint
        assert "CLOUDSMITH_SSL_VERIFY_STRICT=0" in hint

    def test_untrusted_ca_names_the_ca_bundle_variable(self):
        hint = describe_certificate_error(
            certificate_error(20, "unable to get local issuer certificate")
        )

        assert "not from a trusted CA: unable to get local issuer certificate" in hint
        assert "REQUESTS_CA_BUNDLE" in hint
        assert "--without-ssl-verify-strict" not in hint

    def test_other_failures_give_only_the_reason(self):
        hint = describe_certificate_error(
            certificate_error(10, "certificate has expired")
        )

        assert hint == "The TLS certificate is not valid: certificate has expired."

    def test_other_ssl_errors_have_no_hint(self):
        assert describe_certificate_error(ssl.SSLError(1, "EOF")) is None
