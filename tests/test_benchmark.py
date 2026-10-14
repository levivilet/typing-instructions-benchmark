import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from benchmark import (CHARACTER, DEFAULT_ZED_POST_OPEN_SETTLE_SECONDS, PROTOCOL,
                       RESPONSE_WINDOW_SECONDS, is_main_window, saved_content_is_valid,
                       zed_post_open_settle_seconds)
from counters import Capture, parse_counter
import report


def trial(count=100):
    return dict(valid=True, instructions=count, measurementSeconds=1.02,
                inputDispatchSeconds=.02, inputToCutoffSeconds=1.0,
                source='perf stat instructions, per-CPU cgroup',
                character=CHARACTER, savedContent=CHARACTER, focusPid=12,
                pidsAtInput=[12, 14], readiness={'windowId': '1'},
                cutoffAcknowledged=True,
                rawCounter=f'{count};;instructions;typing-test;1234;100.00;;\n')


def result(editor, counts=(100, 300, 200)):
    return dict(editor=editor, protocol=PROTOCOL, host={'machine': 'aarch64'},
                trials=[dict(trial(count), repeat=i + 1) for i, count in enumerate(counts)])


class BenchmarkTest(unittest.TestCase):
    def test_zed_post_open_settle_setting_is_bounded(self):
        self.assertEqual(DEFAULT_ZED_POST_OPEN_SETTLE_SECONDS, 10.0)
        self.assertEqual(zed_post_open_settle_seconds('1'), 1.0)
        self.assertEqual(zed_post_open_settle_seconds('10'), 10.0)
        self.assertEqual(zed_post_open_settle_seconds('0'), 0.0)
        for value in ['-1', '30.1', 'not-a-number']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                zed_post_open_settle_seconds(value)

    def test_protocol_defines_one_character_and_fixed_response_window(self):
        self.assertEqual(PROTOCOL['action'], 'one ASCII x keypress into an empty editor document')
        self.assertEqual(PROTOCOL['responseWindowSeconds'], 1.0)
        self.assertEqual(RESPONSE_WINDOW_SECONDS, 1.0)
        self.assertIn('save verification', PROTOCOL['excluded'])

    def test_saved_content_accepts_only_the_typed_character_and_native_final_lf(self):
        self.assertTrue(saved_content_is_valid('lvce', 'x'))
        self.assertTrue(saved_content_is_valid('geany', 'x\n'))
        self.assertTrue(saved_content_is_valid('zed', 'x\n'))
        self.assertFalse(saved_content_is_valid('lvce', 'x\n'))
        self.assertFalse(saved_content_is_valid('geany', 'x\n\n'))
        self.assertFalse(saved_content_is_valid('zed', 'x\n\n'))
        self.assertFalse(saved_content_is_valid('geany', 'xy'))
        self.assertFalse(saved_content_is_valid('zed', 'xy'))

    def test_main_window_type_defaults_and_rejections(self):
        mapped = 'WM_STATE(WM_STATE):\n    window state: Normal\n'
        missing = '_NET_WM_WINDOW_TYPE:  not found.\nWM_TRANSIENT_FOR:  not found.\n'
        self.assertTrue(is_main_window(mapped + missing))
        self.assertTrue(is_main_window(mapped + '_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_NORMAL'))
        self.assertFalse(is_main_window(missing))
        self.assertFalse(is_main_window(mapped + '_NET_WM_WINDOW_TYPE: not found.\nWM_TRANSIENT_FOR(WINDOW): window id # 0x123'))
        for kind in ['SPLASH', 'DIALOG', 'UTILITY', 'MENU']:
            self.assertFalse(is_main_window(mapped + f'_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_{kind}'))

    def test_control_acknowledgement_formats(self):
        for ack in [b'ack\n', b'ack\n\x00', b'wrong\n']:
            control_read, control_write = os.pipe()
            ack_read, ack_write = os.pipe()
            try:
                os.write(ack_write, ack)
                capture = Capture('unused', '.')
                capture.fds = [control_write, ack_read]
                capture.process = Mock()
                capture.process.poll.return_value = None
                if ack.startswith(b'ack'):
                    capture.control('disable')
                else:
                    with self.assertRaises(RuntimeError):
                        capture.control('disable')
                self.assertEqual(os.read(control_read, 256), b'disable\n')
            finally:
                for fd in [control_read, control_write, ack_read, ack_write]:
                    os.close(fd)

    def test_start_requires_a_disabled_capture_and_acknowledges_enable(self):
        control_read, control_write = os.pipe()
        ack_read, ack_write = os.pipe()
        try:
            os.write(ack_write, b'ack\n')
            capture = Capture('unused', '.')
            capture.fds = [control_write, ack_read]
            capture.process = Mock()
            capture.process.poll.return_value = None
            capture.disabled_at = 1.0
            capture.start()
            self.assertIsNone(capture.disabled_at)
            self.assertEqual(os.read(control_read, 256), b'enable\n')
            with self.assertRaises(RuntimeError):
                capture.start()
        finally:
            for fd in [control_read, control_write, ack_read, ack_write]:
                os.close(fd)

    def test_counter_rejects_unsupported_zero_and_multiplexing(self):
        self.assertEqual(parse_counter('123;;instructions;group;100;100.00;;'), 123)
        for count, running in [('<not supported>', '100'), ('0', '100'), ('123', '50'), ('123', 'nan')]:
            with self.assertRaises(ValueError):
                parse_counter(f'{count};;instructions;group;100;{running};;')
        with self.assertRaises(ValueError):
            parse_counter('123;;instructions;group;100;100;;\n123;;instructions;group;100;100;;')

    def test_report_requires_verified_character_focus_cutoff_and_counter(self):
        editor = report.EDITORS[0]
        data = result(editor)
        report.validate_result(data, editor['id'])
        invalid = [dict(cutoffAcknowledged=False), dict(inputToCutoffSeconds=.1),
                   dict(instructions=101), dict(valid=False), dict(savedContent=''),
                   dict(focusPid=999), dict(diagnosticWarmup=True), dict(character=None), dict(character='y'), dict(savedContent='x\n\n')]
        for changes in invalid:
            broken = copy.deepcopy(data)
            broken['trials'][0].update(changes)
            with self.assertRaises(ValueError):
                report.validate_result(broken, editor['id'])
        data['trials'].pop()
        with self.assertRaises(ValueError):
            report.validate_result(data, editor['id'])

    def test_matrix_must_have_every_editor_and_matching_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                report.load_results(root)
            for editor in report.EDITORS:
                path = root / ('typing-' + editor['id'])
                path.mkdir()
                (path / 'results.json').write_text(json.dumps(result(editor)))
            self.assertEqual(len(report.load_results(root)), len(report.EDITORS))
            path = root / ('typing-' + report.EDITORS[0]['id']) / 'results.json'
            path.write_text(json.dumps(result(dict(report.EDITORS[0], version='wrong'))))
            with self.assertRaises(ValueError):
                report.load_results(root)

    def test_chart_and_report_use_medians_lowest_first_and_keep_raw_trials(self):
        items = []
        for editor, counts in [(report.EDITORS[0], [100, 300, 200]), (report.EDITORS[1], [50, 40, 60])]:
            data = result(editor, counts)
            items.append(dict(editor=editor, data=data))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report.build_report(items, root, 'https://example.test/run', 'commit')
            payload = json.loads((root / 'report.json').read_text())
            self.assertEqual([e['medianInstructions'] for e in payload['editors']], [50, 200])
            chart = report.build_median_chart(payload['editors'])
            self.assertLess(chart.index('VS Code'), chart.index('LVCE Editor'))
            raw = json.loads((root / 'raw/lvce.json').read_text())
            self.assertEqual(raw, items[0]['data'])
            page = (root / 'index.html').read_text()
            self.assertIn('Median instructions per typed character', page)
            self.assertIn('Download JSON', page)


if __name__ == '__main__':
    unittest.main()
