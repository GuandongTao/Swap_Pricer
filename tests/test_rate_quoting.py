import math

import pytest

from swaps.rate_quoting import (
    AnnualCompoundedACT365,
    ContinuousACT360,
    ContinuousACT365,
    SimpleACT360,
    get_rate_quoting,
)


@pytest.mark.parametrize(
    "q",
    [ContinuousACT360(), SimpleACT360(), ContinuousACT365(), AnnualCompoundedACT365()],
)
@pytest.mark.parametrize("rate", [0.0, 0.01, 0.05, 0.10])
@pytest.mark.parametrize("days", [1, 30, 365, 3650])
def test_rate_df_round_trip(q, rate, days):
    df = q.rate_to_df(rate, days)
    assert df > 0
    assert q.df_to_rate(df, days) == pytest.approx(rate, abs=1e-12)


def test_continuous_act360_formula():
    df = ContinuousACT360().rate_to_df(0.05, 360)
    assert df == pytest.approx(math.exp(-0.05))


def test_simple_act360_formula():
    df = SimpleACT360().rate_to_df(0.05, 360)
    assert df == pytest.approx(1.0 / 1.05)


def test_registry_lookup():
    assert get_rate_quoting("ContinuousACT360").name == "ContinuousACT360"
    with pytest.raises(ValueError):
        get_rate_quoting("Bogus")
