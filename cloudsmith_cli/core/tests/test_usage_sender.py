import json
import threading
import time

import pytest

from cloudsmith_cli.core import telemetry_common
from cloudsmith_cli.core.usage import sender

# Captured at import: the autouse conftest guard replaces sender._post.
REAL_POST = sender._post

PAYLOAD = {
    "event": "cli command executed",
    "distinct_id": "x",
    "timestamp": "t",
    "properties": {},
}


def test_send_posts_capture_body(monkeypatch):
    seen = {}

    def fake_post(session, url, body, timeout):
        seen.update(
            url=url,
            body=json.loads(body),
            timeout=timeout,
            headers=dict(session.headers),
        )
        return True

    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", fake_post)
    telemetry_common.WaitBudget.shared().reset(1.0)
    assert sender.send(PAYLOAD) is True
    assert seen["url"] == "https://eu.i.posthog.com/i/v0/e/"
    assert seen["body"]["api_key"] == "phc_test"
    assert seen["timeout"] == sender.REQUEST_TIMEOUT_SECONDS
    assert seen["headers"]["User-Agent"] == sender.USER_AGENT
    assert not any(h.lower().startswith("x-api-key") for h in seen["headers"])


def test_send_session_is_isolated_from_user_settings(monkeypatch):
    import cloudsmith_api

    config = cloudsmith_api.Configuration()
    config.cert_file = "/x/c.pem"
    config.key_file = "/x/k.pem"
    config.verify_ssl = False
    config.error_retry_max = 7
    cloudsmith_api.Configuration.set_default(config)
    seen = {}

    def fake_post(session, url, body, timeout):
        seen.update(
            cert=session.cert,
            verify=session.verify,
            retries=session.get_adapter(url).max_retries.total,
        )
        return True

    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", fake_post)
    telemetry_common.WaitBudget.shared().reset(1.0)
    assert sender.send(PAYLOAD) is True
    assert seen == {"cert": None, "verify": True, "retries": 0}


def test_send_skips_when_budget_is_spent(monkeypatch):
    calls = []
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", lambda *a: calls.append(a) or True)
    telemetry_common.WaitBudget.shared().reset(0.0)
    assert sender.send(PAYLOAD) is None
    assert calls == []


def test_send_skips_when_too_little_budget_is_left(monkeypatch):
    # A POST that cannot finish in time would count as a failure and start
    # the 24 h backoff, so a nearly spent budget sends nothing instead.
    calls = []
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", lambda *a: calls.append(a) or True)
    budget = telemetry_common.WaitBudget.shared()
    budget.reset(sender.MIN_SEND_SECONDS / 2)
    assert sender.send(PAYLOAD) is None
    assert calls == []
    assert budget.remaining() == sender.MIN_SEND_SECONDS / 2


def test_session_setup_is_charged_to_the_budget(monkeypatch):
    # A slow cold start (importing requests and ssl) must not get a full
    # budget on top for the POST.
    real_session = sender._session

    def slow_session(*args):
        time.sleep(0.2)
        return real_session(*args)

    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_session", slow_session)
    monkeypatch.setattr(sender, "_post", lambda *a: True)
    budget = telemetry_common.WaitBudget.shared()
    budget.reset(1.0)
    assert sender.send(PAYLOAD) is True
    assert budget.remaining() <= 0.8


def test_send_skips_when_setup_used_up_the_budget(monkeypatch):
    calls = []
    real_session = sender._session

    def slow_session(*args):
        time.sleep(0.3)
        return real_session(*args)

    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_session", slow_session)
    monkeypatch.setattr(sender, "_post", lambda *a: calls.append(a) or True)
    telemetry_common.WaitBudget.shared().reset(0.4)
    assert sender.send(PAYLOAD) is None
    assert calls == []


@pytest.mark.parametrize("strict, x509_strict_cleared", [(False, True), (None, False)])
def test_session_follows_the_resolved_ssl_strictness(strict, x509_strict_cleared):
    import ssl

    session = sender._session(strict)
    assert session.verify is True  # certificates are always verified
    adapter = session.get_adapter("https://eu.i.posthog.com/")
    has_factory = adapter.ssl_context_factory is not None
    assert has_factory is x509_strict_cleared
    if has_factory:
        assert not adapter.ssl_context_factory().verify_flags & ssl.VERIFY_X509_STRICT


def test_send_reports_failed_post(monkeypatch):
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", lambda *a: False)
    telemetry_common.WaitBudget.shared().reset(1.0)
    assert sender.send(PAYLOAD) is False


def test_send_never_waits_beyond_budget(monkeypatch):
    gate = threading.Event()
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", lambda *a: gate.wait(10))
    telemetry_common.WaitBudget.shared().reset(0.3)
    started = time.monotonic()
    assert sender.send(PAYLOAD) is False
    assert time.monotonic() - started < 0.6
    gate.set()


def test_send_spends_the_shared_budget(monkeypatch):
    gate = threading.Event()
    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", lambda *a: gate.wait(10))
    budget = telemetry_common.WaitBudget.shared()
    budget.reset(0.3)
    assert sender.send(PAYLOAD) is False
    assert budget.remaining() == 0.0
    gate.set()


def test_send_failure_is_silent(monkeypatch, capsys):
    def boom(*a):
        raise RuntimeError("network down")

    monkeypatch.setenv("CLOUDSMITH_TELEMETRY_POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(sender, "_post", boom)
    telemetry_common.WaitBudget.shared().reset(1.0)
    assert sender.send(PAYLOAD) is False
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "status, ok", [(200, True), (204, True), (307, False), (308, False), (400, False)]
)
def test_post_succeeds_on_2xx_only_and_never_follows_redirects(status, ok):
    seen = {}

    class FakeSession:
        def post(self, url, **kwargs):
            seen.update(kwargs)
            return type("Response", (), {"status_code": status})()

    assert REAL_POST(FakeSession(), "https://h/i/v0/e/", "{}", 1.0) is ok
    assert seen["allow_redirects"] is False


def test_log_prints_payload_to_stderr_without_key(capsys):
    sender.log(PAYLOAD)
    out, err = capsys.readouterr()
    assert out == ""
    assert json.loads(err.split("\n", 1)[1])["event"] == "cli command executed"


def test_session_never_sends_netrc_credentials_but_keeps_env_proxies(
    monkeypatch, tmp_path
):
    import requests

    from cloudsmith_cli.core import session as session_module
    from cloudsmith_cli.core.usage import settings

    netrc = tmp_path / ".netrc"
    netrc.write_text("default login nuser password NETRCSECRET\n")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("NO_PROXY", "no_proxy", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setitem(session_module._default_proxy, "url", None)
    url = settings.host() + sender._CAPTURE_PATH

    session = sender._session()
    prepared = session.prepare_request(requests.Request("POST", url, data="{}"))
    assert "Authorization" not in prepared.headers
    env = session.merge_environment_settings(url, {}, None, None, None)
    assert env["proxies"]["https"] == "http://proxy.example:3128"
