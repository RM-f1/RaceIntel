import numpy as np
import pytest

from analytics.stints import normalise_compound


@pytest.mark.parametrize("raw,expected", [
    ("SOFT", "SOFT"), (" medium ", "MEDIUM"), ("None", None), ("nan", None),
    ("UNKNOWN", None), ("", None), (None, None), (np.nan, None),
])
def test_normalise_compound(raw, expected):
    assert normalise_compound(raw) == expected