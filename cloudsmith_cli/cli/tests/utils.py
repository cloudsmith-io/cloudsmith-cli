from datetime import datetime, timezone
from uuid import uuid4


def random_str():
    """Return a random string."""
    return "cli-test-" + str(uuid4())


def random_bool():
    """Return a random bool."""
    return datetime.now(tz=timezone.utc).microsecond % 2 == 0
