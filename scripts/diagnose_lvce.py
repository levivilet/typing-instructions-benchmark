"""Separate no-input controls and sampled profiles from published measurements."""
import argparse
import json
import os
from pathlib import Path
import platform
import select
import signal
import statistics
import subprocess

from benchmark import ROOT, trial
from counters import Capture


class ProfileCapture(Capture):
    def launch(self, command, environment, stdout, stderr, cwd=None):
        # Only the separate diagnostic trial exposes JS names to perf.
        command = [command[0], '--js-flags=--perf-basic-prof --interpreted-frames-native-stack', *command[1:]]
        return super().launch(command, environment, stdout, stderr, cwd)

    def start(self):
        self.profile_log = (self.directory / 'profile.log').open('w')
        self.recorder_fds = []
        for name in ['profile-control', 'profile-ack']:
            path = self.directory / name
            os.mkfifo(path)
            self.recorder_fds.append(os.open(path, os.O_RDWR | os.O_NONBLOCK))
        self.recorder = subprocess.Popen([
            self.perf, 'record', '-a', '-e', 'instructions', '-c', '100000',
            '-G', self.group.name, '--call-graph', 'fp',
            '-D', '-1', '--control', f'fd:{self.recorder_fds[0]},{self.recorder_fds[1]}',
            '-o', str(OUTPUT / 'profile.data'),
        ], pass_fds=tuple(self.recorder_fds), stdout=subprocess.DEVNULL, stderr=self.profile_log)
        os.write(self.recorder_fds[0], b'enable\n')
        if not select.select([self.recorder_fds[1]], [], [], 10)[0]:
            raise RuntimeError('profile recorder did not acknowledge enable')
        if os.read(self.recorder_fds[1], 256) not in (b'ack\n', b'ack\n\x00'):
            raise RuntimeError('invalid profile enable acknowledgement')
        super().start()

    def cutoff(self):
        super().cutoff()
        if hasattr(self, 'recorder'):
            self.recorder.send_signal(signal.SIGINT)
            self.recorder.wait(timeout=10)
            # perf creates root-owned mode-0600 data; artifact upload runs unprivileged.
            (OUTPUT / 'profile.data').chmod(0o644)

    def finish(self):
        result = super().finish()
        result['processes'] = {
            str(pid): Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            for pid in self.pids() if Path(f'/proc/{pid}/cmdline').exists()
        }
        # Resolve V8's /tmp/perf-PID.map while the application's mappings exist.
        with (OUTPUT / 'profile.txt').open('w') as out:
            subprocess.run([self.perf, 'report', '--stdio', '--no-children',
                            '--sort', 'comm,dso,symbol', '-i', str(OUTPUT / 'profile.data')],
                           stdout=out, check=True)
        for pid in self.pids():
            path = Path(f'/tmp/perf-{pid}.map')
            if path.exists():
                (OUTPUT / path.name).write_bytes(path.read_bytes())
        return result

    def __exit__(self, *args):
        try:
            if hasattr(self, 'recorder') and self.recorder.poll() is None:
                self.recorder.send_signal(signal.SIGINT)
                self.recorder.wait(timeout=10)
            if hasattr(self, 'profile_log'):
                self.profile_log.close()
                (OUTPUT / 'profile.log').write_text((self.directory / 'profile.log').read_text())
        finally:
            for fd in getattr(self, 'recorder_fds', []):
                os.close(fd)
            super().__exit__(*args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--perf', required=True)
    args = parser.parse_args()
    if platform.machine() != 'aarch64':
        raise SystemExit('requires Linux ARM64')
    OUTPUT = ROOT / 'results' / 'diagnosis'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    editor = next(e for e in json.loads((ROOT / 'config/editors.lock.json').read_text()) if e['id'] == 'lvce')
    results = {'editor': editor, 'host': {'machine': platform.machine(), 'kernel': platform.release(),
               'cpuinfo': Path('/proc/cpuinfo').read_text(), 'commit': os.environ.get('BENCHMARK_COMMIT')},
               'idle': [], 'typing': []}
    # Alternate order to limit drift. All twelve comparisons are uninstrumented.
    for repeat in range(6):
        for action in (['idle', 'typing'] if repeat % 2 == 0 else ['typing', 'idle']):
            results[action].append(trial(editor, args.perf, idle=action == 'idle'))
            (OUTPUT / 'controls.json').write_text(json.dumps(results, indent=2) + '\n')
    if not all(t['valid'] for action in ['idle', 'typing'] for t in results[action]):
        raise SystemExit('invalid control trials')
    results['medians'] = {action: statistics.median(t['instructions'] for t in results[action])
                          for action in ['idle', 'typing']}
    (OUTPUT / 'controls.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results['medians']))
    results['profileTrial'] = trial(editor, args.perf, capture_type=ProfileCapture)
    (OUTPUT / 'controls.json').write_text(json.dumps(results, indent=2) + '\n')
    if not results['profileTrial']['valid']:
        raise SystemExit('invalid profile trial')
    if '# Samples:' not in (OUTPUT / 'profile.txt').read_text():
        raise SystemExit('profile contains no instruction samples')
