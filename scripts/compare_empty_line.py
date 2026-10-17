"""Compare one diagnostic bundle edit against the exact pinned LVCE artifact."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics

from benchmark import ROOT, trial
from install import download, extract

ANCHOR = '      const oldLine = oldState.lines[rowIndex];\n      const newLine = lines[rowIndex];'
REPLACEMENT = ('      const oldLine = oldState.lines[rowIndex];\n'
               '      if (oldLine.length === 0) {\n        return emptyIncrementalEdits;\n      }\n'
               '      const newLine = lines[rowIndex];')


def patch(source):
    if source.count(ANCHOR) != 1:
        raise ValueError('pinned incremental tokenization anchor is missing or ambiguous')
    return source.replace(ANCHOR, REPLACEMENT)


def digest(contents):
    return hashlib.sha256(contents.encode()).hexdigest()


def verify_released_empty_line_guard(contents):
    start = contents.find('const getIncrementalEdits =')
    if start != -1:
        end = contents.index('\n};', start)
        function = contents[start:end]
        if function.index('oldLine.length === 0') > function.index('const newLine ='):
            raise ValueError('released artifact lacks expected early return')
        return

    label_end = contents.find('"getIncrementalEdits"')
    if label_end == -1:
        raise ValueError('released artifact lacks incremental edit helper')
    start = contents.rfind('=r(async(', 0, label_end)
    if start == -1:
        raise ValueError('released artifact has an unsupported incremental edit helper')
    function = contents[start:label_end]
    if not re.search(r'if\s*\(\s*[\w$]+\.length\s*===\s*0\s*\)\s*return\s+[\w$]+', function):
        raise ValueError('released artifact lacks expected early return')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perf', required=True)
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--released-candidate', action='store_true')
    args = parser.parse_args()
    if args.repeats < 6:
        parser.error('at least six matched trials required')
    if platform.machine() != 'aarch64':
        raise SystemExit('requires Linux ARM64')
    baseline = json.loads((ROOT / 'config/lvce-baseline.lock.json').read_text())
    baseline_root = ROOT / '.tmp/apps/lvce-baseline'
    archive = ROOT / '.tmp' / baseline['archive']
    download(baseline, archive)
    extract(baseline, archive, baseline_root)
    editor = {**baseline, 'binary': '../lvce-baseline/' + baseline['binary']}
    released = next(e for e in json.loads((ROOT / 'config/editors.lock.json').read_text()) if e['id'] == 'lvce')
    files = list(baseline_root.rglob('editorWorkerMain.js'))
    if len(files) != 1:
        raise SystemExit('expected exactly one pinned editor bundle')
    bundle = files[0]
    original = bundle.read_text()
    candidate = original if args.released_candidate else patch(original)
    if args.released_candidate:
        released_files = list((ROOT / '.tmp/apps/lvce').rglob('editorWorkerMain.js'))
        if len(released_files) != 1:
            raise SystemExit('expected one released editor bundle')
        candidate = released_files[0].read_text()
        try:
            verify_released_empty_line_guard(candidate)
        except (ValueError, IndexError) as error:
            raise SystemExit(str(error)) from error
    output = ROOT / 'results' / ('released-artifact-comparison.json' if args.released_candidate else 'empty-line-comparison.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    results = {'editor': editor, 'host': {'machine': platform.machine(), 'kernel': platform.release(),
               'cpuinfo': Path('/proc/cpuinfo').read_text()},
               'diagnosticOnly': True, 'releasedCandidate': released if args.released_candidate else None, 'bundle': str(bundle.relative_to(ROOT)),
               'baselineSha256': digest(original), 'candidateSha256': digest(candidate),
               'change': 'unmodified published Debian artifacts' if args.released_candidate else REPLACEMENT, 'baseline': [], 'candidate': []}
    try:
        # Same runner, same pinned dependencies, no profiler, alternating order.
        for repeat in range(args.repeats):
            for version in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                if not args.released_candidate:
                    bundle.write_text(original if version == 'baseline' else candidate)
                selected = released if args.released_candidate and version == 'candidate' else editor
                result = trial(selected, args.perf)
                result['diagnosticCandidate'] = version
                results[version].append(result)
                output.write_text(json.dumps(results, indent=2) + '\n')
        if not all(t['valid'] for version in ['baseline', 'candidate'] for t in results[version]):
            raise SystemExit('invalid comparison trial')
        results['medians'] = {version: statistics.median(t['instructions'] for t in results[version])
                              for version in ['baseline', 'candidate']}
        output.write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(results['medians']))
    finally:
        if not args.released_candidate:
            bundle.write_text(original)
