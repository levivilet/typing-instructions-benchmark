"""Matched 180-second process-tree CPU trials, separate from first-character instructions."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def workspace_trial(source):
    changes = {
        'command.append(str(fixture))': "command.append(str(fixture.parent if editor['id'] == 'lvce' else fixture))",
        'prepare_lvce_fixture(keyboard, fixture, initial_contents)':
            'keyboard.open_file(fixture.name)\n                prepare_lvce_fixture(keyboard, fixture, initial_contents)',
    }
    for before, after in changes.items():
        if source.count(before) != 1:
            raise ValueError('pinned CPU harness workspace anchor changed')
        source = source.replace(before, after)
    return source


def run(args):
    harness = (ROOT / '.tmp/cpu-harness').resolve()
    lock = json.loads((ROOT / 'config/plaintext-comparison.lock.json').read_text())
    actual = subprocess.check_output(['git', '-C', str(harness), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != lock['cpu']['harnessCommit']:
        raise ValueError('CPU harness revision mismatch')
    output = ROOT / 'results/plaintext-cpu-comparison.json'
    if output.exists():
        raise ValueError('refusing to overwrite CPU evidence')
    sys.path.insert(0, str(harness / 'scripts'))
    import benchmark as b
    import install as installer

    source = inspect.getsource(b.trial)
    adapted = workspace_trial(source)
    exec(compile(adapted, 'matched-workspace-trial.py', 'exec'), b.__dict__)
    target = harness / '.tmp/apps'
    target.mkdir(parents=True, exist_ok=True)
    editors = []
    for entry in [lock['cpu']['lvce'], lock['cpu']['electron']]:
        archive = target / entry['archive']
        installer.download(entry, archive)
        installer.extract(entry, archive, target / entry['id'])
    editors.append(lock['cpu']['lvce'])
    original_entries = json.loads((harness / 'config/editors.lock.json').read_text())
    for editor_id in ['codemirror5', 'codemirror6']:
        entry = next(e for e in original_entries if e['id'] == editor_id)
        runtime = lock['cpu']['electron']
        control = {**entry, **runtime, 'id': editor_id, 'name': entry['name'], 'version': entry['version'],
                   'app': entry['app'], 'binary': str(target / runtime['id'] / runtime['binary']), 'runtimeVersion': runtime['version']}
        subprocess.run(['nice', 'npm', 'ci'], cwd=harness / entry['app'], check=True)
        subprocess.run(['npm', 'run', 'build'], cwd=harness / entry['app'], check=True)
        editors.append(control)
    output.parent.mkdir(parents=True, exist_ok=True)
    b.LOCK = output.parent / 'cpu-editors.json'
    b.LOCK.write_text(json.dumps(editors, indent=2))
    bundle, = (target / 'lvce').rglob('editorWorkerMain.js')
    original = bundle.read_bytes()
    variants = {name: Path(path).read_bytes() for name, path in [('baseline', args.baseline), ('candidate', args.candidate)]}
    if variants['baseline'] == variants['candidate'] or any(data.count(b'\n') < 1000 for data in variants.values()):
        raise ValueError('distinct readable editor bundles are required')
    results = {
        'complete': False, 'runUrl': os.environ.get('BENCHMARK_RUN_URL'), 'commit': os.environ.get('BENCHMARK_COMMIT'), 'lock': lock, 'editors': editors, 'harnessCommit': actual,
        'harnessSourceSha256': hashlib.sha256(source.encode()).hexdigest(), 'workspaceAdapter': adapted,
        'bundles': {name: hashlib.sha256(data).hexdigest() for name, data in variants.items()},
        'host': {'platform': platform.platform(), 'machine': platform.machine(), 'cpuCount': os.cpu_count(),
                 'cpuinfo': Path('/proc/cpuinfo').read_text(), 'clockTicksPerSecond': os.sysconf('SC_CLK_TCK')},
        'protocol': {'sampleSeconds': 180, 'cadenceSeconds': 1, 'idleSeconds': 30, 'repeats': 3,
                     'scope': 'complete application process tree; 100% = one logical CPU',
                     'workspace': 'directory and quick-open; original focus/cadence/exact save gates; fresh XDG and Chromium profiles'},
        'trials': {name: [] for name in ['baseline', 'candidate', 'codemirror5', 'codemirror6']},
    }
    original_measurement = b.typing_measurement
    idle = {}

    def measurement(process, keyboard, fixture, duration, cadence):
        nonlocal idle
        previous = b.process_tree(process.pid)
        started = time.monotonic()
        ticks = 0
        while time.monotonic() - started < 30:
            time.sleep(.25)
            current = b.process_tree(process.pid)
            for pid in current.keys() & previous.keys():
                delta = current[pid] - previous[pid]
                if delta < 0:
                    raise ValueError('idle CPU counter moved backwards')
                ticks += delta
            previous = current
        elapsed = time.monotonic() - started
        idle = {'cpuTicks': ticks, 'elapsedSeconds': elapsed,
                'utilizationPercent': ticks / os.sysconf('SC_CLK_TCK') / elapsed * 100}
        result = original_measurement(process, keyboard, fixture, duration, cadence)
        result['actualSavedContent'] = fixture.read_text()
        result['focusWindow'] = keyboard.window_id
        result['focusPatterns'] = keyboard.focus_patterns
        return result

    b.typing_measurement = measurement
    try:
        for repeat in range(1, 4):
            order = ['baseline', 'candidate', 'codemirror5', 'codemirror6'] if repeat % 2 else ['candidate', 'baseline', 'codemirror6', 'codemirror5']
            for name in order:
                if name in variants:
                    bundle.write_bytes(variants[name])
                    selected = b.load_editor('lvce')
                else:
                    selected = b.load_editor(name)
                result = b.trial(selected, 10, 180, 'xdotool', 1)
                results['trials'][name].append({'repeat': repeat, 'idle': idle, 'typing': result})
                output.write_text(json.dumps(results, indent=2) + '\n')
                if (not result.get('valid') or result.get('inputCount') != 180 or
                        result.get('savedTrailingNewline') or not result.get('savedContentVerified')):
                    raise ValueError(f'invalid {name} trial: {result}')
                print(json.dumps({'variant': name, 'repeat': repeat, 'typingCpu': result['utilizationPercent'], 'idleCpu': idle['utilizationPercent']}), flush=True)
        results['complete'] = True
        results['medians'] = {name: statistics.median(t['typing']['utilizationPercent'] for t in trials)
                              for name, trials in results['trials'].items()}
    finally:
        bundle.write_bytes(original)
        results['restoredOriginalBundle'] = bundle.read_bytes() == original
        output.write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    run(parser.parse_args())
