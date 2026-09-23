"""Track B differential checks on the existing data-free rule fixtures."""
from copy import deepcopy

import pytest

from my_scripts import joint_return_portfolio as portfolio
from my_scripts import joint_return_rule_intents as rules
from my_scripts.joint_return_contract import INTENT_FIELDS, ContractError, canonical_bytes, content_hash, csv_bytes
from test_joint_return_portfolio import seal, snapshot
from test_joint_return_rule_intents import PAIRS, inputs


@pytest.mark.parametrize('topk,n_drop', PAIRS)
@pytest.mark.parametrize('mode', ['full', 'control_only'])
def test_serial_recurrence_and_artifact_bytes(snapshot, monkeypatch, topk, n_drop, mode):
    from test_joint_return_control_only import slim_inputs, seal as slim_seal

    original_step, original_intent = portfolio._step, portfolio._intent

    def checked_step(arm, state, plan, *args, **kwargs):
        before = canonical_bytes(plan)
        expected_hash = content_hash(plan)

        def checked_intent(*intent_args, **intent_kwargs):
            # Catch mutations before any candidate/sell/buy consumes the digest,
            # including a transient mutation later undone before step return.
            assert canonical_bytes(plan) == before
            row = original_intent(*intent_args, **intent_kwargs)
            assert row['source_plan_hash'] == expected_hash
            assert canonical_bytes(plan) == before
            return row

        with monkeypatch.context() as patch:
            patch.setattr(portfolio, '_intent', checked_intent)
            result = original_step(arm, state, plan, *args, **kwargs)
        assert canonical_bytes(plan) == before
        return result

    monkeypatch.setattr(portfolio, '_step', checked_step)
    monkeypatch.setattr(rules, '_step', checked_step)
    s, sessions = (slim_inputs if mode == 'control_only' else inputs)(snapshot, topk, n_drop)
    before = deepcopy((s, sessions))
    slow = rules.generate_plans(s['scores'], s['initial_state'], sessions, s['metadata'])
    fast = rules.generate_plans(s['scores'], s['initial_state'], sessions, s['metadata'], cache_plan_hash=True)
    assert canonical_bytes(fast) == canonical_bytes(slow)
    assert (s, sessions) == before
    s['plans'] = slow['plans']
    (slim_seal if mode == 'control_only' else seal)(s)
    reference = portfolio.build_portfolio(s)
    accelerated = portfolio.build_portfolio(s, cache_plan_hash=True)
    assert canonical_bytes(accelerated) == canonical_bytes(reference)
    assert csv_bytes(accelerated['intents'], INTENT_FIELDS) == csv_bytes(reference['intents'], INTENT_FIELDS)


def test_hash_once_per_step_and_reused_plan_is_rehashed(snapshot, monkeypatch):
    s, sessions = inputs(snapshot)
    ranked = portfolio.score_days(s['scores'])[sessions[0]['date']]
    plan = rules.make_rule_plan('P-BASE', s['initial_state'], {}, ranked, sessions[0], s['metadata'])
    calls = []
    def counted(value):
        if value is plan:
            calls.append(content_hash(value))
        return content_hash(value)
    monkeypatch.setattr(portfolio, 'content_hash', counted)
    def step(cache):
        return portfolio._step('P-BASE', s['initial_state'], plan, ranked, s['metadata'], cache_plan_hash=cache)
    assert canonical_bytes(step(True)) == canonical_bytes(step(False))
    assert len(calls) == 1 + len(plan['buy_candidates']) + len(plan['buys'])
    old_hash = calls[0]
    calls.clear()
    plan['buy_candidates'][-1]['eligibility_reason'] = 'changed fixture reason'
    result = step(True)
    assert calls == [content_hash(plan)] and calls[0] != old_hash
    assert all(row['source_plan_hash'] == calls[0] for row in result[1])
    calls.clear()
    empty = deepcopy(plan)
    empty.update(buy_candidates=[], buys=[])
    plan = empty
    step(True)
    assert calls == []


@pytest.mark.parametrize('with_unapproved_sell', [False, True])
def test_hash_once_with_sells(snapshot, monkeypatch, with_unapproved_sell):
    if with_unapproved_sell:
        s = snapshot
        plan = next(p for p in s['plans'] if p['arm_id'] == 'P-CHASE')
        state = s['initial_state']
        assert any(not order['approved'] for order in plan['sells'])
    else:
        s, sessions = inputs(snapshot)
        generated = rules.generate_plans(s['scores'], s['initial_state'], sessions, s['metadata'])
        record = next(r for r in generated['reference_states']
                      if r['arm_id'] == 'P-CHASE' and r['source_plan']['sells'])
        plan, state = record['source_plan'], record['before']
        assert (len(plan['buy_candidates']), len(plan['sells']), len(plan['buys'])) == (30, 3, 3)
    ranked = portfolio.score_days(s['scores'])[plan['date']]
    before, digest = canonical_bytes(plan), content_hash(plan)
    calls = []

    def counted(value):
        if value is plan:
            calls.append(content_hash(value))
        return content_hash(value)

    monkeypatch.setattr(portfolio, 'content_hash', counted)
    results = []
    for cache in (True, False):
        calls.clear()
        result = portfolio._step('P-CHASE', state, plan, ranked, s['metadata'], cache_plan_hash=cache)
        expected_calls = 1 if cache else len(plan['buy_candidates']) + len(plan['sells']) + len(plan['buys'])
        assert calls == [digest] * expected_calls
        assert canonical_bytes(plan) == before
        assert sum(row['side'] == 'SELL' for row in result[1]) == sum(o['approved'] for o in plan['sells'])
        assert all(row['source_plan_hash'] == digest for row in result[1])
        results.append(result)
    assert canonical_bytes(results[0]) == canonical_bytes(results[1])


@pytest.mark.parametrize('cache', [False, True])
def test_unselected_candidate_still_validated(snapshot, cache):
    s, sessions = inputs(snapshot)
    ranked = portfolio.score_days(s['scores'])[sessions[0]['date']]
    plan = rules.make_rule_plan('P-BASE', s['initial_state'], {}, ranked, sessions[0], s['metadata'])
    assert plan['buy_candidates'][-1]['instrument'] not in plan['buys']
    plan['buy_candidates'][-1]['quantity_unit'] = 'invalid'
    with pytest.raises(ContractError):
        portfolio._step('P-BASE', s['initial_state'], plan, ranked, s['metadata'], cache_plan_hash=cache)


def test_portfolio_cli_accel_is_stamped_and_intents_match(snapshot, tmp_path, capsys):
    import json

    source = tmp_path / 'snapshot.json'
    source.write_bytes(canonical_bytes(snapshot))
    args = ['--snapshot', str(source), '--output-root', str(tmp_path)]
    assert portfolio.main([*args, '--run-id', 'slow']) == 0
    assert portfolio.main([*args, '--run-id', 'fast', '--cache-plan-hash']) == 0
    capsys.readouterr()
    assert (tmp_path / 'slow/intents.csv').read_bytes() == (tmp_path / 'fast/intents.csv').read_bytes()
    manifest = json.loads((tmp_path / 'fast/manifest.json').read_bytes())
    assert manifest['metadata']['research_acceleration'] == 'TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW'
