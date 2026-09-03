"""Repeatable real-Git human acceptance simulation, including the human CLI."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests'))
from test_human_acceptance import HumanAcceptanceTests
from cogito_projection import project_events
import cogito_runtime as runtime

OUT = Path(__file__).resolve().parent

class CLI:
    operations = {'human_feedback': 'feedback', 'human_triage': 'triage',
                  'human_correction_start': 'start', 'human_correction_complete': 'complete',
                  'human_verify': 'verify', 'human_review': 'review', 'human_escalate': 'escalate'}
    def __init__(self, store):
        self.store = store
        self.calls = []
    def __getattr__(self, name):
        if name not in self.operations:
            return getattr(self.store, name)
        def call(*args):
            operation = self.operations[name]
            command = [sys.executable, '-B', str(ROOT / 'scripts/cogito_gate.py'),
                       '--repo', str(self.store.root), 'human', operation,
                       '--run-id', self.store.run_id, '--action-id', args[-1]]
            if operation == 'verify':
                for evidence in args[0]:
                    command += ['--evidence', evidence['evidence_path']]
            elif operation != 'review':
                path = self.store.run_dir / 'simulation-input.json'
                path.write_text(json.dumps(args[0]))
                command += ['--input', str(path)]
            result = subprocess.run(command, capture_output=True, text=True)
            output = json.loads(result.stderr if result.returncode else result.stdout)
            self.calls.append({'operation': operation, 'action_id': args[-1],
                               'ok': output['ok'], 'state': output.get('data', {}).get('state'),
                               'error': output.get('error')})
            if result.returncode:
                raise runtime.CogitoError(output['error'])
            return output['data']
        return call

def trace(store):
    events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
    return [{'event': event['type'], 'state': project_events(events[:i + 1], store.workflow)['state']}
            for i, event in enumerate(events)]

def simulate():
    report = []
    for scenario in ('automatic-close', 'unfinished-acceptance', 'mixed-feedback', 'scope-expansion', 'budget'):
        case = HumanAcceptanceTests()
        case.setUp()
        try:
            repo, original = case.fixture(development_rounds=2 if scenario == 'budget' else 0)
            store = CLI(original)
            if scenario == 'mixed-feedback':
                store.human_feedback(case.feedback(mixed=True), 'mixed')
                store.human_triage({'feedback_id': 'HF-1', 'assessments': [
                    {'id': 'I-1', 'disposition': 'local', 'reason': 'Label typo'},
                    {'id': 'I-2', 'disposition': 'change', 'reason': 'Changes query interaction'},
                ]}, 'classify-mixed')
                try:
                    store.human_correction_start({'amendment_id': 'TA-1'}, 'forbidden-local')
                    raise AssertionError('Mixed feedback incorrectly allowed local repairs')
                except runtime.CogitoError:
                    pass
                case.assertEqual(store.load()['human']['triage']['route'], 'change')
            elif scenario == 'scope-expansion':
                case.begin(store, close=True)
                store.human_escalate({'reason': 'Shared date parser affects other pages'}, 'expand')
                case.assertEqual(store.load()['state'], 'blocked')
            else:
                rounds = 3 if scenario == 'budget' else 1
                for number in range(1, rounds + 1):
                    case.begin(store, number, close=scenario == 'automatic-close')
                    base, head = case.implement(repo, store, number)
                    case.review(repo, store, number, base, head)
                if scenario == 'automatic-close':
                    case.finalize_delivery(repo, store)
                    case.assertEqual(store.completion_report()['status'], 'accepted')
                elif scenario == 'unfinished-acceptance':
                    case.assertEqual(store.load()['state'], 'awaiting-human')
                else:
                    case.assertEqual(case.begin(store, 4)['state'], 'blocked')
                    case.assertEqual(store.load()['counters']['human_corrections'], 3)
                    case.assertEqual(store.load()['counters']['verification_corrections'], 2)
            state = store.load()
            report.append({'scenario': scenario, 'passed': True, 'state': state['state'],
                           'counters': state['counters'], 'next_action': store.next_action(),
                           'cli': store.calls, 'trace': trace(store)})
        finally:
            case.doCleanups()
            case.tearDown()
    (OUT / 'simulation.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps([{'scenario': item['scenario'], 'state': item['state'], 'passed': item['passed']}
                      for item in report], indent=2))

if __name__ == '__main__':
    simulate()
