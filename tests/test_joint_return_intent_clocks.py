"""Calendar-only M-LAG opportunity gates; no minute bars or execution assertions."""
from copy import deepcopy

import pytest

from my_scripts.joint_return_contract import (
    ContractError, next_session_clocks, validate_mlag_window,
)
from my_scripts.joint_return_freeze_snapshot import _validate_sections
from my_scripts.joint_return_portfolio import build_portfolio
from test_joint_return_portfolio import snapshot
from test_joint_return_rule_intents import inputs, generate
from test_joint_return_control_only import slim_inputs, seal as slim_seal
from test_joint_return_portfolio import seal


@pytest.mark.parametrize("slim", [False, True])
def test_bad_host_clocks_rejected_at_each_boundary_without_mutation(snapshot, slim):
    s, sessions = (slim_inputs if slim else inputs)(snapshot)
    good = generate(s, sessions)
    bad = dict(available_at="2026-09-07T15:03:00+08:00",
               effective_at="2026-09-07T15:03:00+08:00",
               expires_at="2026-09-07T16:00:00+08:00")
    sessions[0].update(bad)
    original = deepcopy(sessions)
    with pytest.raises(ContractError, match="PAIR_INVALID.*no possible M-LAG open"):
        generate(s, sessions)
    assert sessions == original
    s["plans"] = good["plans"]
    s["plans"][0].update(bad)
    (slim_seal if slim else seal)(s)
    for boundary in (_validate_sections, build_portfolio):
        original = deepcopy(s)
        with pytest.raises(ContractError, match="PAIR_INVALID.*no possible M-LAG open"):
            boundary(s)
        assert s == original


@pytest.mark.parametrize("available,effective,expires,valid", [
    ("09:30:00", "09:30:00", "09:31:00", False),  # expiry is exclusive
    ("09:30:00", "09:30:00", "09:31:01", True),
    ("09:30:01", "09:31:01", "09:32:00", False),
    ("09:30:01", "09:31:01", "09:32:01", True),
    ("11:29:00", "11:29:00", "13:00:00", False),  # lunch has no opens
    ("11:29:00", "11:29:00", "13:00:01", True),
    ("14:59:00", "14:59:00", "16:00:00", False),
    ("15:03:00", "15:03:00", "16:00:00", False),
])
def test_minute_grid_lunch_effective_and_exclusive_boundaries(available, effective, expires, valid):
    day = "2026-09-07"
    clocks = {k: f"{day}T{v}+08:00" for k, v in
              zip(("available_at", "effective_at", "expires_at"), (available, effective, expires))}
    metadata = {"calendar": [day]}
    if valid:
        validate_mlag_window(clocks, metadata)
    else:
        with pytest.raises(ContractError, match="PAIR_INVALID.*no possible M-LAG open"):
            validate_mlag_window(clocks, metadata)


def test_next_session_helper_uses_only_explicit_dates_and_preserves_inputs():
    # Deliberately skip days: do not calculate weekdays or fill a calendar gap.
    metadata = {"calendar": ["2026-09-11"], "execution_calendar": ["2026-09-11", "2026-09-16"]}
    original = deepcopy(metadata)
    args = dict(decision_at="2026-09-11T15:02:00+08:00", mark_at="2026-09-11T15:00:00+08:00")
    clocks = next_session_clocks(**args, metadata=metadata)
    assert metadata == original
    assert clocks == {**args, "available_at": "2026-09-16T09:30:00+08:00",
                      "effective_at": "2026-09-16T09:30:00+08:00",
                      "expires_at": "2026-09-16T15:00:00+08:00"}
    del metadata["execution_calendar"]
    with pytest.raises(ContractError, match="INPUT_BLOCKED.*next session missing"):
        next_session_clocks(**args, metadata=metadata)
    with pytest.raises(ContractError, match="no possible M-LAG open"):
        validate_mlag_window(clocks, metadata)


@pytest.mark.parametrize("calendar,match", [
    ([], "required"), (["2026-09-07", "2026-09-07"], "duplicates"),
    (["2026-09-08", "2026-09-07"], "order"), (["2026-09-08"], "missing research"),
    (["2026-09-07", "invalid"], "date"),
])
def test_invalid_execution_calendar_fails_closed(calendar, match):
    with pytest.raises(ContractError, match=match):
        next_session_clocks(decision_at="2026-09-07T15:02:00+08:00",
                            mark_at="2026-09-07T15:00:00+08:00",
                            metadata={"calendar": ["2026-09-07"], "execution_calendar": calendar})


def test_explicit_cross_close_window_passes_without_shifting():
    clocks = dict(available_at="2026-09-07T15:03:00+08:00",
                  effective_at="2026-09-08T09:30:00+08:00",
                  expires_at="2026-09-08T09:30:01+08:00")
    original = deepcopy(clocks)
    validate_mlag_window(clocks, {"calendar": ["2026-09-07", "2026-09-08"]})
    assert clocks == original  # 09:30 is strictly after the prior day's availability
