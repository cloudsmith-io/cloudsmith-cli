"""Tests for the translation of SDK API errors."""

from unittest.mock import patch

import pytest
from cloudsmith_api.rest import ApiException as SdkApiException

from ..api.exceptions import ApiException, catch_raise_api_exception
from ..api.user import get_user_token


class _FakeHttpResponse:
    status = 400
    reason = "Bad Request"

    def __init__(self, data: bytes):
        self.data = data

    def getheaders(self) -> dict[str, str]:
        return {}


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (b'["Cannot read.", {"code": 1}, "Try again."]', "Cannot read. Try again."),
        (b'"Cannot read."', "Cannot read."),
        (b"null", "Bad Request"),
        (b'{"detail": "Invalid.", "fields": ["name"]}', "Invalid."),
    ],
)
def test_error_body_of_any_json_shape_keeps_the_status(body, detail):
    with pytest.raises(ApiException) as exc_info:
        with catch_raise_api_exception():
            raise SdkApiException(http_resp=_FakeHttpResponse(body))

    assert exc_info.value.status == 400
    assert exc_info.value.detail == detail
    assert exc_info.value.fields == {}


def test_two_factor_check_ignores_a_list_body():
    error = SdkApiException(
        http_resp=_FakeHttpResponse(b'[{"two_factor_required": true}]')
    )
    error.status = 422

    with patch("cloudsmith_cli.core.api.user.get_user_api") as get_user_api:
        get_user_api.return_value.user_token_create_with_http_info.side_effect = error
        with pytest.raises(ApiException) as exc_info:
            get_user_token("you@example.com", "secret")

    assert exc_info.value.status == 422
