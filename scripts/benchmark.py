"""Measure retired CPU instructions for one verified editor keystroke."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time
from counters import Capture

ROOT = Path(__file__).resolve().parent.parent
CHARACTER = 'x'
RESPONSE_WINDOW_SECONDS = 1.0
PROTOCOL = {
    'version': 3,
    'metric': 'retired hardware instructions (user and kernel)',
    'action': 'one ASCII x keypress into an empty editor document',
    'boundary': 'acknowledged perf enable immediately before key injection through acknowledged disable 1.0 seconds after injection',
    'responseWindowSeconds': RESPONSE_WINDOW_SECONDS,
    'accounting': 'per-CPU cgroup; includes editor descendants and all work during the response window',
    'excluded': 'launch, document setup, focus setup, the external input driver, save verification, and cleanup',
    'profile': 'fresh HOME and XDG directories for every trial',
    'cache': 'warm OS filesystem caches permitted; application profiles always fresh',
    'launcher': 'editor cgroup contains editor process tree; controller, X server, desktop, and xdotool stay outside',
    'cutoff': 'perf disable acknowledgement after fixed response window; control latency through acknowledgement is included',
    'verification': 'save after cutoff and verify the fixture contains exactly x; Geany and Zed may add one documented final LF on save',
    'repeats': 3,
}


def command_for(editor, home, fixture):
    binary = str(ROOT / '.tmp/apps' / editor['id'] / editor['binary'])
    editor_id = editor['id']
    if editor_id == 'geany':
        return ['geany', '--new-instance', str(fixture)]
    args = []
    if editor_id in {'lvce', 'vscode', 'basic-electron'}:
        args += ['--no-sandbox', '--disable-gpu', '--ozone-platform=x11']
    if editor_id in {'lvce', 'vscode', 'zed'}:
        args += ['--user-data-dir', str(home / 'profile')]
    if editor_id == 'vscode':
        args += ['--disable-extensions', '--skip-welcome', '--skip-release-notes', '--disable-workspace-trust']
    if editor_id == 'lapce':
        args += ['--new', '--wait']
    if editor_id == 'basic-electron':
        args += [str(ROOT / 'basic-electron'), str(fixture)]
    else:
        args += [str(fixture)]
    return [binary, *args]


def saved_content_is_valid(editor_id, contents):
    return contents == CHARACTER or (editor_id in {'geany', 'zed'} and contents == CHARACTER + '\n')


def is_main_window(properties):
    lines = properties.splitlines()
    type_line = next((line for line in lines if line.startswith('_NET_WM_WINDOW_TYPE')), '')
    transient_line = next((line for line in lines if line.startswith('WM_TRANSIENT_FOR')), '')
    managed = 'window state: Normal' in properties
    normal = '_NET_WM_WINDOW_TYPE_NORMAL' in type_line
    default_normal = (type_line.partition(':')[2].strip() == 'not found.' and
                      transient_line.partition(':')[2].strip() == 'not found.')
    return managed and (normal or default_normal)


def visible_window(pids):
    for pid in pids:
        search = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(pid)],
                                capture_output=True, text=True)
        for window in search.stdout.split():
            props = subprocess.check_output(['xprop', '-id', window, '_NET_WM_WINDOW_TYPE',
                                             'WM_NAME', 'WM_CLASS', '_NET_WM_PID', 'WM_TRANSIENT_FOR', 'WM_STATE'], text=True)
            if is_main_window(props):
                return {'windowId': window, 'pid': pid, 'properties': props}
    return None


def trial(editor, perf):
    with tempfile.TemporaryDirectory(prefix='typing-trial-') as directory:
        d = Path(directory)
        home = d / 'home'
        home.mkdir()
        fixture = d / 'typing-fixture.txt'
        fixture.write_text('')
        env = {**os.environ, 'HOME': str(home), 'LC_ALL': 'C', 'LIBGL_ALWAYS_SOFTWARE': '1',
               'GALLIUM_DRIVER': 'llvmpipe', 'ZED_ALLOW_EMULATED_GPU': '1',
               'ELECTRON_OZONE_PLATFORM_HINT': 'x11'}
        for key, name in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                          ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state'),
                          ('XDG_RUNTIME_DIR', 'runtime')]:
            env[key] = str(home / name)
            (home / name).mkdir()
        (home / 'runtime').chmod(0o700)
        if 'SUDO_UID' in env:
            uid, gid = int(env['SUDO_UID']), int(env['SUDO_GID'])
            for path in [d, home, fixture, *home.iterdir()]:
                os.chown(path, uid, gid)
        command = command_for(editor, home, fixture)
        details = {'stage': 'launch', 'command': command, 'fixture': str(fixture)}
        failure_diagnostics = {}
        try:
            with Capture(perf, d) as capture:
                # Startup, window discovery, settling and focus are excluded.
                capture.cutoff()
                with (d / 'stdout').open('w') as stdout, (d / 'stderr').open('w') as stderr:
                    child = capture.launch(command, env, stdout, stderr, cwd=d)
                    start = time.monotonic()
                    while True:
                        pids = capture.pids()
                        if not pids:
                            raise RuntimeError(f'editor exited before main window: {child.poll()}')
                        window = visible_window(pids)
                        if window:
                            break
                        if time.monotonic() - start > 120:
                            failure_diagnostics = {'reason': 'main window readiness timeout'}
                            raise RuntimeError('main window readiness timeout')
                        time.sleep(.02)
                    time.sleep(10)
                    window_id = window['windowId']
                    details.update(window=window, pids=pids, stage='settle')
                    subprocess.run(['xdotool', 'windowactivate', '--sync', window_id], check=True)
                    if editor['id'] == 'zed':
                        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+p'], check=True)
                        subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '0', '--', fixture.name], check=True)
                        time.sleep(.5)
                        subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Return'], check=True)
                        time.sleep(1)
                        title = subprocess.check_output(['xdotool', 'getwindowname', window_id], text=True).strip()
                        if fixture.name not in title:
                            raise RuntimeError(f'Zed did not open fixture {fixture.name}: {title!r}')
                    positions = {'basic-electron': ('200', '160'), 'lapce': ('500', '150'),
                                 'zed': ('800', '135')}
                    x, y = positions.get(editor['id'], ('500', '400'))
                    subprocess.run(['xdotool', 'mousemove', '--window', window_id, x, y], check=True)
                    subprocess.run(['xdotool', 'click', '1'], check=True)
                    focused_window = subprocess.check_output(['xdotool', 'getwindowfocus'], text=True).strip()
                    focused_pid = int(subprocess.check_output(['xdotool', 'getwindowpid', focused_window], text=True).strip())
                    pids = capture.pids()
                    details.update(focusWindow=focused_window, focusPid=focused_pid, pids=pids, stage='input')
                    if focused_pid not in pids:
                        raise RuntimeError(f'focus is outside editor cgroup: window={focused_window}, pid={focused_pid}')
                    time.sleep(.5)
                    capture.start()
                    measured_started = time.monotonic()
                    subprocess.run(['xdotool', 'key', '--clearmodifiers', CHARACTER], check=True)
                    input_sent = time.monotonic()
                    remaining = input_sent + RESPONSE_WINDOW_SECONDS - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    capture.cutoff()
                    result = capture.finish()
                    result.update(valid=True, readiness=window,
                                  character=CHARACTER, focusWindow=focused_window,
                                  focusPid=focused_pid, pidsAtInput=pids,
                                  inputDispatchSeconds=input_sent-measured_started,
                                  inputToCutoffSeconds=capture.disabled_at-input_sent,
                                  measurementSeconds=capture.disabled_at-measured_started,
                                  command=command)
                    details.update(measurement={key: result.get(key) for key in
                                    ('instructions', 'measurementSeconds', 'inputDispatchSeconds', 'inputToCutoffSeconds')},
                                   stage='save')
                    subprocess.run(['xdotool', 'key', '--clearmodifiers', 'ctrl+s'], check=True)
                    deadline = time.monotonic() + 5
                    while not saved_content_is_valid(editor['id'], fixture.read_text()) and time.monotonic() < deadline:
                        time.sleep(.05)
                    saved = fixture.read_text()
                    details['savedContent'] = saved
                    if not saved_content_is_valid(editor['id'], saved):
                        raise RuntimeError(f'saved fixture mismatch: expected {CHARACTER!r}, got {saved!r}')
                    result['savedContent'] = saved
            child.wait(timeout=5)
            return result
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            return {'valid': False, 'error': str(error), 'command': command,
                    'diagnostics': {**details, **failure_diagnostics},
                    **{name: (d / name).read_text(errors='replace')[-8000:]
                       for name in ['stdout', 'stderr', 'perf.log'] if (d / name).exists()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editor', required=True)
    parser.add_argument('--perf', required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error('at least three trials required')
    editor = next(e for e in json.loads((ROOT / 'config/editors.lock.json').read_text()) if e['id'] == args.editor)
    host = {'machine': platform.machine(), 'kernel': platform.release(), 'cpuinfo': Path('/proc/cpuinfo').read_text(),
            'perf': subprocess.check_output([args.perf, '--version'], text=True).strip(),
            'eventSources': sorted(p.name for p in Path('/sys/bus/event_source/devices').iterdir()),
            'paranoid': Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip(),
            'editorUid': int(os.environ.get('SUDO_UID', os.getuid())),
            'runUrl': os.environ.get('BENCHMARK_RUN_URL'), 'commit': os.environ.get('BENCHMARK_COMMIT')}
    if host['machine'] != 'aarch64':
        raise SystemExit('requires Linux ARM64')
    if editor.get('package'):
        host['packageVersion'] = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', editor['package']], text=True)
    trials = [dict(trial(editor, args.perf), repeat=i+1) for i in range(args.repeats)]
    Path('results').mkdir(exist_ok=True)
    Path('results/results.json').write_text(json.dumps(dict(editor=editor, protocol=PROTOCOL, host=host, trials=trials), indent=2)+'\n')
    if not all(t['valid'] for t in trials):
        raise SystemExit('invalid trials; cannot publish complete report')

if __name__ == '__main__':
    main()
