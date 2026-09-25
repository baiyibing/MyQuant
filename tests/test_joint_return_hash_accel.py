"""Track B differential checks on the existing data-free rule fixtures."""
import json
from copy import deepcopy

import pytest

from my_scripts import joint_return_portfolio as portfolio
from my_scripts import joint_return_rule_intents as rules
from my_scripts.joint_return_contract import INTENT_FIELDS, ContractError, canonical_bytes, content_hash, csv_bytes, raw_hash
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


def test_rule_cli_cache_defaults_and_artifacts_match(request, tmp_path, capsys, monkeypatch):
    s, sessions = inputs(request.getfixturevalue('snapshot'))
    args = []
    for name, value in [('scores', s['scores']), ('initial_state', s['initial_state']), ('sessions', sessions)]:
        path = tmp_path / f'{name}.json'
        data = canonical_bytes(value) + b'\n'
        path.write_bytes(data)
        args += [f'--{name.replace("_", "-")}', str(path)]
        if name in ('scores', 'initial_state'):
            s['metadata']['inputs'][name].update(
                uri=str(path.resolve()), raw_sha256=raw_hash(data), content_sha256=content_hash(value))
    metadata_path = tmp_path / 'metadata.json'
    metadata_path.write_bytes(canonical_bytes(s['metadata']) + b'\n')
    args += ['--metadata', str(metadata_path)]

    original_generate = rules.generate_plans
    cache_options = []

    def capture_generate(*args, cache_plan_hash, **kwargs):
        cache_options.append(cache_plan_hash)
        return original_generate(*args, cache_plan_hash=cache_plan_hash, **kwargs)

    monkeypatch.setattr(rules, 'generate_plans', capture_generate)
    plans, manifests, metadata = [], [], []
    for name, flags, cache in [('default', [], True), ('slow', ['--no-cache-plan-hash'], False),
                               ('fast', ['--cache-plan-hash'], True)]:
        output = tmp_path / name
        assert rules.main([*args, '--output-dir', str(output), *flags]) == 0
        capsys.readouterr()
        plans.append((output / 'plans.json').read_bytes())
        manifest = json.loads((output / 'rule-manifest.json').read_bytes())
        current_metadata = json.loads((output / 'metadata.json').read_bytes())
        assert ('research_acceleration' in current_metadata) is cache
        assert current_metadata.pop('research_acceleration', None) == (
            'TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW' if cache else None)
        assert current_metadata['inputs']['plans'].pop('uri') == str((output / 'plans.json').resolve())
        assert manifest['plans'].pop('uri') == str((output / 'plans.json').resolve())
        metadata.append(current_metadata)
        manifests.append(manifest)
    assert cache_options == [True, False, True]
    assert plans[0] == plans[1] == plans[2]
    assert manifests[0]['reference_states'] == manifests[1]['reference_states'] == manifests[2]['reference_states']
    assert manifests[0] == manifests[1] == manifests[2]
    assert metadata[0] == metadata[1] == metadata[2]


@pytest.mark.parametrize('flag', ['--cache-plan-hash', '--no-cache-plan-hash'])
def test_rule_cli_boolean_error_stays_input_blocked(tmp_path, capsys, flag):
    args = [arg for name in ('scores', 'initial-state', 'sessions', 'metadata')
            for arg in (f'--{name}', str(tmp_path / f'{name}.json'))]
    assert rules.main([*args, '--output-dir', str(tmp_path / 'out'), f'{flag}=true']) == 2
    error = json.loads(capsys.readouterr().out)
    assert error['status'] == 'INPUT_BLOCKED'
    assert "ignored explicit argument 'true'" in error['detail']
    assert not (tmp_path / 'out').exists()


def test_portfolio_cli_accel_is_stamped_and_intents_match(snapshot, tmp_path, capsys, monkeypatch):
    original_run = portfolio.run_snapshot
    cache_options = []

    def capture_run(*args, cache_plan_hash, **kwargs):
        cache_options.append(cache_plan_hash)
        return original_run(*args, cache_plan_hash=cache_plan_hash, **kwargs)

    monkeypatch.setattr(portfolio, 'run_snapshot', capture_run)

    source = tmp_path / 'snapshot.json'
    source.write_bytes(canonical_bytes(snapshot))
    args = ['--snapshot', str(source), '--output-root', str(tmp_path)]
    manifests = []
    for run_id, flags, cache in [('default', [], True), ('slow', ['--no-cache-plan-hash'], False),
                                 ('fast', ['--cache-plan-hash'], True)]:
        assert portfolio.main([*args, '--run-id', run_id, *flags]) == 0
        capsys.readouterr()
        manifest = json.loads((tmp_path / run_id / 'manifest.json').read_bytes())
        assert manifest.pop('run_id') == run_id
        assert ('research_acceleration' in manifest['metadata']) is cache
        assert manifest['metadata'].pop('research_acceleration', None) == (
            'TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW' if cache else None)
        manifests.append(manifest)
    assert cache_options == [True, False, True]
    for name in ('intents.csv', 'constraints.csv', 'pref_check.json'):
        assert ((tmp_path / 'default' / name).read_bytes() == (tmp_path / 'slow' / name).read_bytes()
                == (tmp_path / 'fast' / name).read_bytes())
    assert manifests[0] == manifests[1] == manifests[2]
