from unittest.mock import MagicMock, patch

import pytest
import requests

from ...core.api.exceptions import ApiException
from ..saml import exchange_2fa_token, get_idp_url, refresh_access_token


@pytest.fixture
def mock_response():
    with patch("requests.Response", autospec=True) as MockResponse:
        yield MockResponse.return_value


@pytest.fixture
def mock_session():
    session = MagicMock(spec=requests.sessions.Session)
    return session


class TestSaml:
    api_host = "https://example.com"

    # urlencoded params {"redirect_url": "http://localhost:12400"}
    query_params = "redirect_url=http%3A%2F%2Flocalhost%3A12400"

    def test_get_idp_url(self, mock_response, mock_session):
        mock_response.json.return_value = {"redirect_url": "response_redirect_url"}
        mock_session.get.return_value = mock_response

        assert (
            get_idp_url(self.api_host, "test_org", session=mock_session)
            == "response_redirect_url"
        )
        mock_session.get.assert_called_once_with(
            f"{self.api_host}/orgs/test_org/saml/?{self.query_params}", timeout=30
        )

    def test_get_idp_url_with_request_error(self, mock_response, mock_session):
        mock_session.get.return_value = mock_response
        mock_response.status_code = 500
        mock_response.headers = {"foo": "bar"}
        mock_response.content = "Error body"
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "An error occurred", response=mock_response
        )

        with pytest.raises(ApiException) as exc:
            get_idp_url(self.api_host, "test_org", session=mock_session)

            assert exc == ApiException(
                status=500, headers={"foo": "bar"}, body="Error body"
            )
            mock_session.get.assert_called_once_with(
                f"{self.api_host}/orgs/test_org/saml/?{self.query_params}", timeout=30
            )

    def test_exchange_2fa_token(self, mock_response, mock_session):
        mock_session.post.return_value = mock_response
        mock_response.json.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
        }

        assert exchange_2fa_token(
            self.api_host,
            "two_factor_token",
            "totp_token",
            session=mock_session,
        ) == (
            "access_token",
            "refresh_token",
        )
        mock_session.post.assert_called_once_with(
            f"{self.api_host}/user/two-factor/",
            data={"two_factor_token": "two_factor_token", "totp_token": "totp_token"},
            headers={"Authorization": "Bearer two_factor_token"},
            timeout=30,
        )

    def test_exchange_2fa_token_with_request_error(self, mock_response, mock_session):
        mock_session.post.return_value = mock_response
        mock_response.status_code = 500
        mock_response.headers = {"foo": "bar"}
        mock_response.content = "Error body"
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "An error occurred", response=mock_response
        )

        with pytest.raises(ApiException) as exc:
            exchange_2fa_token(
                self.api_host,
                "two_factor_token",
                "totp_token",
                session=mock_session,
            )

            assert exc == ApiException(
                status=500, headers={"foo": "bar"}, body="Error body"
            )
            mock_session.post.assert_called_once_with(
                f"{self.api_host}/user/two-factor/",
                data={
                    "two_factor_token": "two_factor_token",
                    "totp_token": "totp_token",
                },
                headers={"Authorization": "Bearer two_factor_token"},
                timeout=30,
            )

    def test_refresh_access_token(self, mock_response, mock_session):
        mock_session.post.return_value = mock_response
        mock_response.json.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
        }

        assert refresh_access_token(
            self.api_host,
            "access_token",
            "refresh_token",
            session=mock_session,
        ) == (
            "access_token",
            "refresh_token",
        )
        mock_session.post.assert_called_once_with(
            f"{self.api_host}/user/refresh-token/",
            data={"refresh_token": "refresh_token"},
            headers={"Authorization": "Bearer access_token"},
            timeout=30,
        )

    def test_refresh_access_token_with_request_error(self, mock_response, mock_session):
        mock_session.post.return_value = mock_response
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
            exchange_2fa_token(
                self.api_host,
                "two_factor_token",
                "totp_token",
                session=mock_session,
            )

            assert exc == ApiException(
                status=500, headers={"foo": "bar"}, body="Error body"
            )
            mock_session.post.assert_called_once_with(
                f"{self.api_host}/user/refresh-token/",
                data={"refresh_token": "refresh_token"},
                headers={"Authorization": "Bearer access_token"},
                timeout=30,
            )
