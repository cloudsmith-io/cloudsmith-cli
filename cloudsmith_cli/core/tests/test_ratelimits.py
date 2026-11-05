from ..ratelimits import RateLimitsInfo


def test_from_dict_treats_null_values_as_missing():
    info = RateLimitsInfo.from_dict(
        {
            "interval": None,
            "limit": None,
            "remaining": None,
            "reset": None,
            "throttled": None,
        }
    )

    assert info.interval is None
    assert info.limit is None
    assert info.remaining is None
    assert info.reset is None
    assert info.throttled is False
