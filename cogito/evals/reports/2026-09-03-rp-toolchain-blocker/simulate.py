#!/usr/bin/env python3
"""Reproduce RP blockers using disposable Git fixtures; never touch a real run."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import types
from pathlib import Path

COGITO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COGITO / 'tests'))
from test_replan_runtime_snapshot import ReplanRuntimeSnapshotTests
from cogito_common import CogitoError
from cogito_test_support import git


class Scenario(ReplanRuntimeSnapshotTests):
    def fixture(self):
        repo, worker, source, ranges = super().fixture()
        tool = repo / '.codex/skills/cogito/scripts/cogito_gate.py'
        tool.parent.mkdir(parents=True)
        tool.write_text('# frozen tool implementation\n')
        git(repo, 'add', '.codex/skills/cogito')
        git(repo, 'commit', '-qm', 'Install in-repository workflow tool')
        return repo, worker, source, ranges


def run_scenario(legacy, change, old_store=None):
    case = Scenario()
    case.setUp()
    try:
        repo, worker, source, rp, _, _ = case.stopped(legacy=legacy)
        successor, proposal = case.prepare_successor(repo, source)
        snapshot = copy.deepcopy(rp.load()['snapshot'])
        rp_events = rp.events_path.read_bytes()
        source_events = source.events_path.read_bytes()
        successor_events = successor.events_path.read_bytes()
        source_package = source.approved_package()
        candidate_hash = successor.load()['candidate_package_hash']
        worker_head = git(worker, 'rev-parse', 'HEAD')
        tool = repo / '.codex/skills/cogito/scripts/cogito_gate.py'
        if change in ('tool', 'committed-tool'):
            tool.write_text('# upgraded tool implementation\n')
        elif change == 'product':
            (repo / 'src/a.txt').write_text('unauthorized product change\n')
        if change == 'committed-tool':
            git(repo, 'add', '.codex/skills/cogito')
            git(repo, 'commit', '-qm', 'Upgrade workflow tool during RP')
        error = None
        try:
            if old_store:
                # Execute the actual pre-fix Store guard, with today's test
                # fixture/dependency modules. This is a boundary reproduction,
                # not a full historical-release end-to-end evaluation.
                old_store(repo, rp.replan_id)._assert_source(proposal)
            else:
                rp.propose(proposal, 'simulate-propose')
        except CogitoError as exc:
            error = str(exc)
        expected = ('delivery content drifted outside new control documents'
                    if old_store or change in ('tool', 'product') else
                    'delivery baseline drifted since stop checkpoint'
                    if change == 'committed-tool' else None)
        if expected:
            case.assertIsNotNone(error)
            case.assertIn(expected, error)
            case.assertEqual(rp.load()['state'], 'analyzing')
            case.assertFalse(rp.load().get('proposal_hash'))
            case.assertEqual(rp.events_path.read_bytes(), rp_events)
            if change == 'tool':
                case.assertIn('.codex/skills/cogito/scripts/cogito_gate.py', error)
                case.assertNotIn('.cogito/', error)
        else:
            case.assertIsNone(error)
            case.assertEqual(rp.load()['state'], 'reviewing')
            case.assertTrue(rp.events_path.read_bytes().startswith(rp_events))
        case.assertEqual(rp.load()['snapshot'], snapshot)
        case.assertEqual(source.events_path.read_bytes(), source_events)
        case.assertEqual(successor.events_path.read_bytes(), successor_events)
        case.assertEqual(source.approved_package(), source_package)
        case.assertEqual(successor.load()['candidate_package_hash'], candidate_hash)
        case.assertEqual(successor.load()['state'], 'awaiting-package-approval')
        case.assertEqual(git(worker, 'rev-parse', 'HEAD'), worker_head)
        case.assertEqual(git(worker, 'status', '--porcelain'), '')
        return dict(snapshot='legacy' if legacy else 'current', change=change,
                    guard='pre-fix' if old_store else 'current', result='PASS',
                    observed_error=error, state=rp.load()['state'],
                    snapshot_and_source_and_candidate_preserved=True)
    finally:
        case.doCleanups()


def main():
    root = COGITO.parent
    old_revision = git(root, 'rev-parse', 'cdce97c^')
    old_code = subprocess.run(
        ['git', '-C', str(root), 'show', old_revision + ':cogito/scripts/cogito_replan_store.py'],
        text=True, capture_output=True, check=True).stdout
    old_module = types.ModuleType('historical_replan_store')
    exec(compile(old_code, '<historical_replan_store>', 'exec'), old_module.__dict__)
    results = [run_scenario(True, 'runtime-only', old_module.ReplanStore)]
    for legacy in (False, True):
        for change in ('runtime-only', 'tool', 'committed-tool', 'product'):
            results.append(run_scenario(legacy, change))
    report = dict(current_revision=git(root, 'rev-parse', 'HEAD'),
                  historical_store_revision=old_revision, passed=len(results),
                  method='Temporary real Git fixtures and Store calls; historical guard uses current dependency modules; approvals in source fixture are synthetic.',
                  scenarios=results)
    Path(__file__).with_name('simulation.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
