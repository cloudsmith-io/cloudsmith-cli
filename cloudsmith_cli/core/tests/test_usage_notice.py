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
    assert "usage data" in err and "CLOUDSMITH_NO_TELEMETRY" in err
    # The notice names the install ID and how to see and reset it.
    assert "install ID" in err
    assert "cloudsmith telemetry id" in err and "cloudsmith telemetry reset" in err
    assert state.read()["notice_version"] == notice.NOTICE_VERSION


def test_notice_version_bumped_for_the_install_id():
    assert notice.NOTICE_VERSION >= 2
