from datetime import datetime
from uuid import uuid4


def random_str():
    """Return a random string."""
    return "cli-test-" + str(uuid4())


def random_bool():
    """Return a random bool."""
    return datetime.now(tz=datetime.timezone.utc).microsecond % 2 == 0
