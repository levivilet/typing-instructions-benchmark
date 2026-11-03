"""Compare identical LVCE artifacts with baseline/candidate editor-worker bundles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess

from benchmark import ROOT, PROTOCOL, trial
from install import download, extract


def installed_editor(entry, installation):
    return {**entry, 'binary': str((installation / entry['binary']).resolve())}


def validate_trial(result, *, idle=False):
    if not result.get('valid'):
        raise ValueError(f'invalid trial: {result}')
    if result.get('diagnosticWarmup'):
        raise ValueError('warm-up cannot establish first-character savings')
    if result.get('savedContent') != ('' if idle else 'x'):
        raise ValueError('exact saved input is required')
    if not result.get('cutoffAcknowledged') or result.get('inputToCutoffSeconds', 0) < 1:
        raise ValueError('one-second acknowledged cutoff is required')
    if result.get('focusPid') not in result.get('pidsAtInput', []):
        raise ValueError('focus must belong to the editor cgroup')
    if idle:
        usage = result.get('cpuUsageUsec')
        if not isinstance(usage, int) or usage < 0:
            raise ValueError('a nonnegative cgroup CPU-time delta is required for idle controls')
    elif not isinstance(result.get('instructions'), int) or result['instructions'] <= 0:
        raise ValueError('positive retired instructions are required')


def run(args):
    if platform.machine() != 'aarch64':
        raise RuntimeError('comparison requires Linux ARM64')
    lock = json.loads((ROOT / 'config/plaintext-comparison.lock.json').read_text())
    output = ROOT / 'results/plaintext-comparison.json'
    if output.exists():
        raise RuntimeError('refusing to overwrite comparison evidence')
    target = ROOT / '.tmp/apps'
    target.mkdir(parents=True, exist_ok=True)
    lvce = lock['lvce']
    archive = target / lvce['archive']
    download(lvce, archive)
    extract(lvce, archive, target / 'lvce-comparison')
    editor = installed_editor(lvce, target / 'lvce-comparison')
    electron = lock['electron']
    archive = target / electron['archive']
    download(electron, archive)
    extract(electron, archive, target / electron['id'])
    entries = json.loads((ROOT / 'config/editors.lock.json').read_text())
    controls = []
    for editor_id in ['codemirror5', 'codemirror6']:
        original = next(e for e in entries if e['id'] == editor_id)
        control = installed_editor({**original, 'binary': electron['binary'], 'runtime': electron}, target / electron['id'])
        app = ROOT / original['app']
        subprocess.run(['nice', 'npm', 'ci'], cwd=app, check=True)
        subprocess.run(['npm', 'run', 'build'], cwd=app, check=True)
        controls.append(control)
    bundle, = (target / 'lvce-comparison').rglob('editorWorkerMain.js')
    original = bundle.read_bytes()
    variants = {name: Path(path).read_bytes() for name, path in [('baseline', args.baseline), ('candidate', args.candidate)]}
    if variants['baseline'] == variants['candidate']:
        raise ValueError('candidate must differ from baseline')
    if any(data.count(b'\n') < 1000 for data in variants.values()):
        raise ValueError('production bundles must remain readable')
    results = {
        'protocol': PROTOCOL, 'diagnosticOnly': True,
        'workspace': 'valid directory; quick-open empty fixture without edits; preserve actual HOME, fresh XDG and Chromium profiles',
        'lock': lock, 'bundles': {name: hashlib.sha256(data).hexdigest() for name, data in variants.items()},
        'host': {'machine': platform.machine(), 'kernel': platform.release(), 'cpuinfo': Path('/proc/cpuinfo').read_text(),
                 'perf': subprocess.check_output([args.perf, '--version'], text=True).strip()},
        'runUrl': os.environ.get('BENCHMARK_RUN_URL'),
        'baseline': [], 'candidate': [], 'idle': [], 'controls': [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(results, indent=2) + '\n')

    try:
        for repeat in range(args.repeats):
            for version in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                bundle.write_bytes(variants[version])
                result = trial(editor, args.perf, lvce_workspace=True)
                result.update(diagnosticCandidate=version, repeat=repeat + 1)
                results[version].append(result)
                save()
                validate_trial(result)
        for version in ['baseline', 'candidate']:
            bundle.write_bytes(variants[version])
            for repeat in range(3):
                result = trial(editor, args.perf, idle=True, lvce_workspace=True)
                result.update(diagnosticCandidate=version, repeat=repeat + 1)
                results['idle'].append(result)
                save()
                validate_trial(result, idle=True)
        for control in controls:
            for repeat in range(3):
                result = trial(control, args.perf)
                result.update(editor=control, repeat=repeat + 1)
                results['controls'].append(result)
                save()
                validate_trial(result)
        results['medians'] = {name: statistics.median(r['instructions'] for r in results[name]) for name in variants}
        results['pairedSavings'] = [a['instructions'] - b['instructions'] for a, b in zip(results['baseline'], results['candidate'])]
        save()
        print(json.dumps(results['medians']), flush=True)
    finally:
        bundle.write_bytes(original)
        results['restoredOriginalBundle'] = bundle.read_bytes() == original
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perf', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--repeats', type=int, default=30)
    args = parser.parse_args()
    if args.repeats < 6:
        parser.error('at least six alternating pairs are required')
    run(args)
