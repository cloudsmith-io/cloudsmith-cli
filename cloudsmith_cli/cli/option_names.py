"""CLI - Names of options that are also read outside their decorators.

Usage telemetry reads these before, or without, the decorator that declares
them (``--version``, ``--help`` and usage errors never reach it), so the
decorator and telemetry share one spelling of each name. Keep this module
free of imports: it is loaded on every command.
"""

#: ``decorators.initialise_session``
API_HOST = "--api-host"
API_HOST_ENV = "CLOUDSMITH_API_HOST"
SSL_VERIFY = "--ssl-verify"
WITHOUT_SSL_VERIFY = "--without-ssl-verify"
SSL_VERIFY_ENV = "CLOUDSMITH_SSL_VERIFY"
#: Read by the deprecated ``--without-api-ssl-verify`` spelling.
WITHOUT_SSL_VERIFY_LEGACY_ENV = "CLOUDSMITH_WITHOUT_API_SSL_VERIFY"

#: ``decorators.common_cli_config_options``
CONFIG_FILE = ("-C", "--config-file")
CONFIG_FILE_ENV = "CLOUDSMITH_CONFIG_FILE"
CREDENTIALS_FILE_ENV = "CLOUDSMITH_CREDENTIALS_FILE"
PROFILE = ("-P", "--profile")
PROFILE_ENV = "CLOUDSMITH_PROFILE"
