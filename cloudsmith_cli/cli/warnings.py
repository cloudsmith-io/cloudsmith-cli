from abc import ABC
from typing import Dict, List


class CliWarning(ABC):
    """
    Abstract base class for all Cloudsmith CLI warnings.
    """

    def __repr__(self):
        return self.__str__()

    def __hash__(self):
        return hash(self.__str__())

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False

        return self.__dict__ == other.__dict__


class ConfigLoadWarning(CliWarning):
    """
    Warning for issues loading the configuration file.
    """

    def __init__(self, paths: Dict[str, bool]):
        self.paths = paths
        self.message = "Failed to load config files. Tried the following paths: \n"
        for path, exists in paths.items():
            self.message += f"  - {path} - exists: {exists}\n"
        self.message += "You may need to run `cloudsmith login` to authenticate and create a config file. \n"

    def __str__(self):
        return f"{self.__class__.__name__} - {self.paths}"


class ProfileNotFoundWarning(CliWarning):
    """
    Warning for issues finding the requested profile.
    """

    def __init__(self, paths, profile):
        self.path = paths
        self.profile = profile
        self.message = f"Failed to load profile {profile} from config. Tried the following paths: \n"
        for path, exists in paths.items():
            self.message += f"  - {path} - exists: {exists}\n"

    def __str__(self):
        return f"{self.__class__.__name__} - {self.path} - {self.profile}"


class ApiAuthenticationWarning(CliWarning):
    """
    Warning for issues with API authentication.
    """

    def __init__(self, cloudsmith_host):
        self.cloudsmith_host = cloudsmith_host
        self.message = "".join(
            [
                "Failed to authenticate with Cloudsmith API ",
                "Please check your credentials and try again.\n",
                f"Host: {cloudsmith_host}\n",
            ]
        )

    def __str__(self):
        return f"{self.__class__.__name__} - {self.cloudsmith_host}"


class CliWarnings(list):
    """
    A class to manage warnings in the CLI.
    """

    def __init__(self):
        super().__init__()
        self.warnings: List[CliWarning] = []

    def append(self, warning: CliWarning):
        self.warnings.append(warning)

    def __dedupe__(self) -> List[CliWarning]:
        return list(set(self.warnings))

    def display(self, display_fn):
        for warning in self.__dedupe__():
            display_fn(warning.message)

    def __repr__(self) -> str:
        return self.__str__()

    def __str__(self) -> str:
        return ",".join([str(x) for x in self.warnings])

    def __len__(self) -> int:
        return len(self.warnings)


def get_or_create_warnings(ctx):
    """Get or create the warnings object."""

    return ctx.ensure_object(CliWarnings)
