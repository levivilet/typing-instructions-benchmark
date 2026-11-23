"""Compare packaged LVCE and CodeMirror 5 with interleaved focused idle controls."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess

from benchmark import PROTOCOL, ROOT, trial
from compare_plaintext import installed_editor, validate_trial
import diagnose_lvce
from install import download, extract


def run(args):
    if platform.machine() != 'aarch64':
        raise RuntimeError('comparison requires Linux ARM64')
    output = ROOT / 'results/packaged-typing.json'
    if output.exists():
        raise RuntimeError('refusing to overwrite comparison evidence')
    output.parent.mkdir(parents=True, exist_ok=True)

    locked = {item['id']: item for item in json.loads((ROOT / 'config/editors.lock.json').read_text())}
    versions = json.loads((ROOT / 'config/packaged-typing.lock.json').read_text())
    variants = {key: {**locked[spec['id']], **spec} for key, spec in versions.items()}
    target = ROOT / '.tmp/apps'
    target.mkdir(parents=True, exist_ok=True)
    editors = {}
    for key, variant in variants.items():
        archive = target / variant['archive']
        download(variant, archive)
        extract(variant, archive, target / key)
        editors[key] = installed_editor(variant, target / key)

    results = {
        'protocol': {**PROTOCOL, 'repeats': args.repeats},
        'variants': variants,
        'host': {'machine': platform.machine(), 'kernel': platform.release(),
                 'cpuinfo': Path('/proc/cpuinfo').read_text(),
                 'perf': subprocess.check_output([args.perf, '--version'], text=True).strip()},
        'runUrl': os.environ.get('BENCHMARK_RUN_URL'),
        'commit': os.environ.get('BENCHMARK_COMMIT'),
        'trials': [],
        'profiles': {},
    }

    def save():
        output.write_text(json.dumps(results, indent=2) + '\n')

    cases = [(key, idle) for key in editors for idle in (False, True)]
    for repeat in range(args.repeats):
        offset = (repeat // 2 * 2) % len(cases)
        order = cases[offset:] + cases[:offset]
        for key, idle in (order if repeat % 2 == 0 else reversed(order)):
            result = trial(editors[key], args.perf, idle=idle)
            results['trials'].append({'variant': key, 'idle': idle, 'repeat': repeat + 1, **result})
            save()
            validate_trial(result, idle=idle)

    results['summary'] = {}
    for key in editors:
        groups = {}
        for idle in (False, True):
            trials = [item for item in results['trials'] if item['variant'] == key and item['idle'] == idle]
            counts = [item['instructions'] for item in trials if item['instructions'] is not None]
            groups['idle' if idle else 'typing'] = {
                'counted': len(counts),
                'uncounted': len(trials) - len(counts),
                'median': statistics.median(counts) if counts else None,
                'min': min(counts) if counts else None,
                'max': max(counts) if counts else None,
            }
            if idle:
                groups['idle']['medianCpuUsec'] = statistics.median(item['cpuUsageUsec'] for item in trials)
        results['summary'][key] = groups
    save()
    print(json.dumps(results['summary']), flush=True)

    for key in ('lvce-current', 'cm5-matched'):
        diagnose_lvce.OUTPUT = output.parent / f'profile-{key}'
        diagnose_lvce.OUTPUT.mkdir()
        result = trial(editors[key], args.perf, capture_type=diagnose_lvce.ProfileCapture)
        results['profiles'][key] = result
        save()
        validate_trial(result)
        if '# Samples:' not in (diagnose_lvce.OUTPUT / 'profile.txt').read_text():
            raise RuntimeError(f'no instruction samples for {key}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perf', required=True)
    parser.add_argument('--repeats', type=int, default=8)
    args = parser.parse_args()
    if args.repeats < 6:
        parser.error('at least six repeats are required')
    run(args)
