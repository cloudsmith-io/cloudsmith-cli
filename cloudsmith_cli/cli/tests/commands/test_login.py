import pytest

from ...commands.login import login


@pytest.mark.usefixtures("set_api_host_env_var")
class TestLoginCommand:
    def test_login_via_prompt(self, runner, username, password, api_key):
        """Test that a user can `cloudsmith login` with interactive prompts."""
        expected = "Your API key/token is: %s" % api_key
        user_input = [
            username,  # Login:
            password,  # Password:
            password,  # Repeat for confirmation:
            "N",  # No default config file(s) found, do you want to create them? [y/N]:
        ]
        result = runner.invoke(login, input="\n".join(user_input))
        assert not result.exception
        assert result.exit_code == 0
        assert expected in result.stdout

    def test_login_via_args(self, runner, username, password, api_key):
        """Test that a user can `cloudsmith login -l <login> -p <password>`."""
        expected = "Your API key/token is: %s" % api_key
        # The "input" argument here answers the following prompt:
        # No default config file(s) found, do you want to create them? [y/N]:
        result = runner.invoke(login, ["-l", username, "-p", password], input="N\n")
        assert not result.exception
        assert result.exit_code == 0
        assert expected in result.stdout
