from cloudsmith_cli.core.usage import notice, state


def test_needs_notice_until_current_version_recorded(usage_state_dir):
    assert notice.needs_notice() is True
    state.write({"notice_version": notice.NOTICE_VERSION})
    assert notice.needs_notice() is False
    state.write({"notice_version": notice.NOTICE_VERSION - 1})
    assert notice.needs_notice() is True


def test_show_prints_to_stderr_only(usage_state_dir, capsys):
    assert notice.show() is True
    out, err = capsys.readouterr()
    assert out == ""
    assert "usage data" in err
    # The details and the opt-outs live on the docs page; the notice links it.
    assert "https://docs.cloudsmith.com/developer-tools/cli-telemetry" in err
    assert "opt out" in err
    assert state.read()["notice_version"] == notice.NOTICE_VERSION


def test_notice_version_bumped_for_the_install_id():
    assert notice.NOTICE_VERSION >= 2
