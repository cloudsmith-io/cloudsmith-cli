from unittest.mock import patch

import pytest
import requests

from ...core.api.exceptions import ApiException
from ..saml import exchange_2fa_token, get_idp_url, refresh_access_token


@pytest.fixture
def mock_get_request():
    with patch.object(requests, "get") as mock_get:
        yield mock_get


@pytest.fixture
def mock_post_request():
    with patch.object(requests, "post") as mock_post:
        yield mock_post


@pytest.fixture
def mock_response():
    with patch("requests.Response", autospec=True) as MockResponse:
        yield MockResponse.return_value


class TestSaml:
    api_host = "https://example.com"

    # urlencoded params {"redirect_url": "http://localhost:12400"}
    query_params = "redirect_url=http%3A%2F%2Flocalhost%3A12400"

    def test_get_idp_url(self, mock_get_request, mock_response):
        mock_get_request.return_value = mock_response
        mock_response.json.return_value = {"redirect_url": "response_redirect_url"}

        assert get_idp_url(self.api_host, "test_org") == "response_redirect_url"
        mock_get_request.assert_called_once_with(
            f"{self.api_host}/orgs/test_org/saml/?{self.query_params}", timeout=30
        )

    def test_get_idp_url_with_request_error(self, mock_get_request, mock_response):
        mock_get_request.return_value = mock_response
        mock_response.status_code = 500
        mock_response.headers = {"foo": "bar"}
        mock_response.content = "Error body"
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "An error occurred", response=mock_response
        )

        with pytest.raises(ApiException) as exc:
            get_idp_url(self.api_host, "test_org")

            assert exc == ApiException(
                status=500, headers={"foo": "bar"}, body="Error body"
            )
            mock_get_request.assert_called_once_with(
                f"{self.api_host}/orgs/test_org/saml/?{self.query_params}", timeout=30
            )

    def test_exchange_2fa_token(self, mock_post_request, mock_response):
        mock_post_request.return_value = mock_response
        mock_response.json.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
        }

        assert exchange_2fa_token(self.api_host, "two_factor_token", "totp_token") == (
            "access_token",
            "refresh_token",
        )
        mock_post_request.assert_called_once_with(
            f"{self.api_host}/user/two-factor/",
            data={"two_factor_token": "two_factor_token", "totp_token": "totp_token"},
            headers={"Authorization": "Bearer two_factor_token"},
            timeout=30,
        )

    def test_exchange_2fa_token_with_request_error(
        self, mock_post_request, mock_response
    ):
        mock_post_request.return_value = mock_response
        mock_response.status_code = 500
        mock_response.headers = {"foo": "bar"}
        mock_response.content = "Error body"
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "An error occurred", response=mock_response
        )

        with pytest.raises(ApiException) as exc:
            exchange_2fa_token(self.api_host, "two_factor_token", "totp_token")

            assert exc == ApiException(
                status=500, headers={"foo": "bar"}, body="Error body"
            )
            mock_post_request.assert_called_once_with(
                f"{self.api_host}/user/two-factor/",
                data={
                    "two_factor_token": "two_factor_token",
                    "totp_token": "totp_token",
                },
                headers={"Authorization": "Bearer two_factor_token"},
                timeout=30,
            )

    def test_refresh_access_token(self, mock_post_request, mock_response):
        mock_post_request.return_value = mock_response
        mock_response.json.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
        }

        assert refresh_access_token(self.api_host, "access_token", "refresh_token") == (
            "access_token",
            "refresh_token",
        )
        mock_post_request.assert_called_once_with(
            f"{self.api_host}/user/refresh-token/",
            data={"refresh_token": "refresh_token"},
            headers={"Authorization": "Bearer access_token"},
            timeout=30,
        )

    def test_refresh_access_token_with_request_error(
        self, mock_post_request, mock_response
    ):
        mock_post_request.return_value = mock_response
        mock_response.status_code = 500
        mock_response.headers = {"foo": "bar"}
        mock_response.content = "Error body"
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "An error occurred", response=mock_response
        )
        mock_response.json.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
        }

        with pytest.raises(ApiException) as exc:
            exchange_2fa_token(self.api_host, "two_factor_token", "totp_token")

            assert exc == ApiException(
                status=500, headers={"foo": "bar"}, body="Error body"
            )
            mock_post_request.assert_called_once_with(
                f"{self.api_host}/user/refresh-token/",
                data={"refresh_token": "refresh_token"},
                headers={"Authorization": "Bearer access_token"},
                timeout=30,
            )
