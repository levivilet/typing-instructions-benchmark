"""Compare one diagnostic bundle edit against the exact pinned LVCE artifact."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics

from benchmark import ROOT, trial

ANCHOR = '      const oldLine = oldState.lines[rowIndex];\n      const newLine = lines[rowIndex];'
REPLACEMENT = ANCHOR + '\n      if (oldLine.length === 0) {\n        return emptyIncrementalEdits;\n      }'


def patch(source):
    if source.count(ANCHOR) != 1:
        raise ValueError('pinned incremental tokenization anchor is missing or ambiguous')
    return source.replace(ANCHOR, REPLACEMENT)


def digest(contents):
    return hashlib.sha256(contents.encode()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perf', required=True)
    args = parser.parse_args()
    if platform.machine() != 'aarch64':
        raise SystemExit('requires Linux ARM64')
    files = list((ROOT / '.tmp/apps/lvce').rglob('editorWorkerMain.js'))
    if len(files) != 1:
        raise SystemExit('expected exactly one pinned editor bundle')
    bundle = files[0]
    original = bundle.read_text()
    candidate = patch(original)
    editor = next(e for e in json.loads((ROOT / 'config/editors.lock.json').read_text()) if e['id'] == 'lvce')
    output = ROOT / 'results' / 'empty-line-comparison.json'
    results = {'editor': editor, 'host': {'machine': platform.machine(), 'kernel': platform.release(),
               'cpuinfo': Path('/proc/cpuinfo').read_text()},
               'diagnosticOnly': True, 'bundle': str(bundle.relative_to(ROOT)),
               'baselineSha256': digest(original), 'candidateSha256': digest(candidate),
               'change': REPLACEMENT, 'baseline': [], 'candidate': []}
    try:
        # Same runner, same pinned dependencies, no profiler, alternating order.
        for repeat in range(6):
            for version in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                bundle.write_text(original if version == 'baseline' else candidate)
                result = trial(editor, args.perf)
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
        bundle.write_text(original)
