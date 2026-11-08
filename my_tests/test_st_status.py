"""MyQuant eligibility consumes infra's dated ST observations."""
from datetime import date

import pandas as pd

from buy_eligibility import BuyEligibilityFilter
from myquant_infra.reference_data.st.readers import load_st_codes_asof


def test_dense_non_st_day_clears_previous_hit(tmp_path):
    daily = tmp_path / "st_daily.parquet"
    pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-01-07", "2026-01-08"]),
        "code": ["000615.SZ", "000615.SZ"],
        "is_st": [True, False],
    }).to_parquet(daily, index=False)
    assert load_st_codes_asof(daily, asof="2026-01-07") == {"SZ000615"}
    assert load_st_codes_asof(daily, asof="2026-01-08") == set()
    eligibility = BuyEligibilityFilter(st_daily_file=daily)
    assert eligibility._st_by_date[date(2026, 1, 7)] == {"SZ000615"}
    assert eligibility._st_by_date[date(2026, 1, 8)] == set()
    assert eligibility.st_fallback == set()
