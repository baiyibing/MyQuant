"""Linux fixture benchmark, not research market data.

Run from repo root: PYTHONPATH=tests:. python tests/benchmark_joint_return_hash_accel.py
Each mode/day pair runs in a fresh subprocess; timings exclude fixture setup.
"""
import argparse
from copy import deepcopy
import json
import resource
import subprocess
import sys
import time
import types

from my_scripts import joint_return_portfolio as portfolio
from my_scripts import joint_return_rule_intents as rules
from my_scripts.joint_return_contract import INTENT_FIELDS, canonical_bytes, csv_bytes, raw_hash, sort_intents
from test_joint_return_portfolio import snapshot
from test_joint_return_rule_intents import inputs


def measure(mode, days):
    generate, step = rules.generate_plans, portfolio._step
    if mode == 'original':
        modules = []
        for name in ('joint_return_portfolio', 'joint_return_rule_intents'):
            module = types.ModuleType(name)
            source = subprocess.check_output(['git', 'show', f'1c1fe43:my_scripts/{name}.py'])
            exec(compile(source, f'1c1fe43/{name}.py', 'exec'), module.__dict__)
            modules.append(module)
        modules[1]._step = modules[0]._step
        generate, step = modules[1].generate_plans, modules[0]._step
    kwargs = {'cache_plan_hash': True} if mode == 'cached' else {}
    s, sessions = inputs(snapshot.__wrapped__())
    s['metadata']['calendar'] = s['metadata']['calendar'][:days]
    s['scores'] = [r for r in s['scores'] if r['date'] in s['metadata']['calendar']]
    sessions = sessions[:days]
    wall, cpu = time.perf_counter(), time.process_time()
    out = generate(s['scores'], s['initial_state'], sessions, s['metadata'], **kwargs)
    generation = time.perf_counter() - wall
    grouped = portfolio.score_days(s['scores'])
    states = {a: deepcopy(s['initial_state']) for a in out['final_states']}
    intents = []
    for plan in out['plans']:
        arm = plan['arm_id']
        states[arm], rows, _, _ = step(arm, states[arm], plan, grouped[plan['date']], s['metadata'], **kwargs)
        intents.extend(rows)
    artifacts = {'plans': canonical_bytes(out['plans']) + b'\n',
                 'product': canonical_bytes(out) + b'\n',
                 'intents': csv_bytes(sort_intents(intents), INTENT_FIELDS)}
    elapsed, used = time.perf_counter() - wall, time.process_time() - cpu
    return dict(mode=mode, days=days, generation_s=generation, wall_s=elapsed, cpu_s=used,
                cpu_wall=used/elapsed, peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                candidates=[len(p['buy_candidates']) for p in out['plans']],
                hashes={k: raw_hash(v) for k, v in artifacts.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['original', 'reference', 'cached'])
    parser.add_argument('--days', type=int, choices=[1, 5], default=5)
    args = parser.parse_args()
    if args.mode:
        print(json.dumps(measure(args.mode, args.days), sort_keys=True))
    else:
        for days in (1, 5):
            results = [json.loads(subprocess.check_output([
                sys.executable, __file__, '--mode', mode, '--days', str(days)]))
                for mode in ('original', 'reference', 'cached')]
            assert results[0]['hashes'] == results[1]['hashes'] == results[2]['hashes']
            for result in results:
                print(json.dumps(result, sort_keys=True), flush=True)
