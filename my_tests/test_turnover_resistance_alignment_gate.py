# -*- coding: utf-8 -*-
"""Data-free exit-policy tests for the lake-backed TR alignment gate."""

from __future__ import annotations

import pytest
from myquant_factors import _runtime

@pytest.fixture
def alignment_exit_code(monkeypatch, tmp_path):
    monkeypatch.setitem(_runtime._ports, "research_root", lambda: tmp_path)
    from myquant_factors.research.entries.gates.verify_turnover_resistance_alignment import alignment_exit_code
    return alignment_exit_code


def test_alignment_exit_code_requires_both_metrics(alignment_exit_code) -> None:
    assert alignment_exit_code(3, 3, 3) == 0
    assert alignment_exit_code(3, 2, 3) == 2
    assert alignment_exit_code(3, 3, 2) == 2
    assert alignment_exit_code(3, 2, 2) == 2


def test_alignment_exit_code_rejects_zero_valid_samples(alignment_exit_code) -> None:
    assert alignment_exit_code(0, 0, 0) == 1
