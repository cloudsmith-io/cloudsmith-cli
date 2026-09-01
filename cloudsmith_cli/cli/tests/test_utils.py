import click
import pytest

from ..utils import confirm_operation, maybe_truncate_list, maybe_truncate_string


@pytest.mark.parametrize(
    "data,max_length,expected_len",
    [(range(1), 5, 1), (range(5), 5, 5), ([], 5, 0), (None, 5, 0)],
)
def test_maybe_truncate_list(data, max_length, expected_len):
    truncated = maybe_truncate_list(data, max_length)

    if data is None:
        assert truncated is None
    else:
        assert len(truncated) == expected_len

    if expected_len > max_length:
        assert truncated[:-1] == "..."


@pytest.mark.parametrize(
    "data,max_length,expected_len",
    [("test", 10, 4), ("test" * 5, 10, 10), ("", 10, 0), (None, 10, 0)],
)
def test_maybe_truncate_string(data, max_length, expected_len):
    truncated = maybe_truncate_string(data, max_length)

    if data is None:
        assert truncated is None
    else:
        assert len(truncated) == expected_len

    if expected_len > max_length:
        assert truncated[-4:-1] == "..."


class TestConfirmOperation:
    """The prompt's preamble is opt-out, so a command can ask directly."""

    @staticmethod
    def prompt_for(monkeypatch, **kwargs):
        asked = []
        monkeypatch.setattr(
            "click.confirm", lambda text, **_: asked.append(text) or True
        )
        monkeypatch.setattr(
            "click.get_text_stream",
            lambda name: type("S", (), {"isatty": lambda self: True})(),
        )
        confirm_operation("do the thing", **kwargs)
        return click.unstyle(asked[0])

    def test_the_default_preamble_is_unchanged(self, monkeypatch):
        assert self.prompt_for(monkeypatch) == (
            "Are you absolutely certain you want to do the thing?"
        )

    def test_an_empty_prefix_asks_the_question_on_its_own(self, monkeypatch):
        assert self.prompt_for(monkeypatch, prefix="") == "do the thing?"

    def test_a_given_prefix_still_wins(self, monkeypatch):
        assert self.prompt_for(monkeypatch, prefix="Really") == "Really do the thing?"

    def test_assume_yes_never_asks(self, monkeypatch):
        monkeypatch.setattr(
            "click.confirm", lambda *a, **k: pytest.fail("should not have asked")
        )
        assert confirm_operation("do the thing", prefix="", assume_yes=True) is True
