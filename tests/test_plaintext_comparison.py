import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from benchmark import command_for
from compare_plaintext import validate_trial


class PlaintextComparisonTest(unittest.TestCase):
    def test_directory_launch_is_opt_in_and_controls_keep_file_argument(self):
        fixture = Path('/tmp/workspace/typing-fixture.txt')
        editor = {'id': 'lvce', 'binary': 'usr/lib/lvce/lvce'}
        self.assertEqual(command_for(editor, Path('/tmp/profile'), fixture)[-1], str(fixture))
        self.assertEqual(command_for(editor, Path('/tmp/profile'), fixture, lvce_workspace=True)[-1], str(fixture.parent))
        control = {'id': 'codemirror5', 'binary': 'electron'}
        self.assertEqual(command_for(control, Path('/tmp/profile'), fixture, lvce_workspace=True)[-1], str(fixture))

    def test_diagnostic_acceptance_rejects_missing_input_focus_cutoff_and_warmup(self):
        valid = {'valid': True, 'diagnosticWarmup': False, 'savedContent': 'x', 'cutoffAcknowledged': True,
                 'inputToCutoffSeconds': 1.01, 'focusPid': 12, 'pidsAtInput': [12, 13], 'instructions': 123}
        validate_trial(valid)
        validate_trial({**valid, 'savedContent': ''}, idle=True)
        for changes in [{'valid': False}, {'savedContent': ''}, {'savedContent': 'xx'}, {'savedContent': 'x\n'},
                        {'cutoffAcknowledged': False}, {'inputToCutoffSeconds': .5}, {'focusPid': 99},
                        {'instructions': 0}, {'diagnosticWarmup': True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_trial({**copy.deepcopy(valid), **changes})

class WorkspaceAdapterTest(unittest.TestCase):
    def test_adapter_preserves_measurement_body_and_fails_on_changed_harness(self):
        from compare_plaintext_cpu import workspace_trial
        source = ("command.append(str(fixture))\n"
                  "                prepare_lvce_fixture(keyboard, fixture, initial_contents)\n"
                  "measurement = typing_measurement(process, keyboard, fixture, sample_seconds, cadence_seconds)")
        adapted = workspace_trial(source)
        self.assertIn("fixture.parent if editor['id'] == 'lvce' else fixture", adapted)
        self.assertIn('keyboard.open_file(fixture.name)', adapted)
        self.assertIn('measurement = typing_measurement(process, keyboard, fixture, sample_seconds, cadence_seconds)', adapted)
        for invalid in ['', source + source]:
            with self.assertRaises(ValueError):
                workspace_trial(invalid)


if __name__ == '__main__':
    unittest.main()
