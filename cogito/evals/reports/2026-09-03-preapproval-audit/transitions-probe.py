"""Read-only product audit: real CLI in disposable Git fixtures."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'scripts')]
from test_package_revisions import PackageRevisionTests, GATE
from cogito_run_store import RunStore

out = []
case = PackageRevisionTests()
case.setUp()
try:
    repo, package, draft = case.fixture('feature')
    run_id = package['run_id']
    def cli(name, *args, expected=0, unchanged=False):
        events = repo / '.cogito/runs' / run_id / 'events.jsonl'
        before = events.read_bytes()
        cmd = [sys.executable, str(GATE), '--repo', str(repo), *args]
        result = subprocess.run(cmd, text=True, capture_output=True)
        row = dict(name=name, command=cmd, returncode=result.returncode,
                   stdout=result.stdout, stderr=result.stderr,
                   events_unchanged=events.read_bytes() == before)
        out.append(row)
        assert result.returncode == expected, row
        if unchanged: assert row['events_unchanged'], row
        return json.loads(result.stdout)['data'] if expected == 0 else None
    cli('prepare initial package', 'prepare-package', '--run-id', run_id, '--package', str(draft), '--action-id', 'prepare-initial')
    for name, event, payload in [
        ('cannot resubmit shared understanding', 'shared-understanding-ready', {'shared_understanding_hash':'c'*64}),
        ('cannot reconfirm shared understanding', 'shared-understanding-confirmed', {'confirmed':True}),
        ('cannot rerun boundary completion', 'boundary-complete', package['boundary']),
        ('no replan workflow event', 'replan', {'target':'preparing'}),
    ]:
        cli(name, 'transition', '--run-id', run_id, '--event', event, '--payload-json', json.dumps(payload), '--action-id', name.replace(' ','-'), expected=2, unchanged=True)
    cli('RP rejects unapproved source', 'replan', 'begin', '--replan-id', 'RP-preapproval', '--source-run', run_id, '--successor-run', 'DEV-successor', '--reason', 'User requests filters only', '--action-id', 'rp-begin', expected=2, unchanged=True)
    assert not (repo / '.cogito/replans/RP-preapproval/events.jsonl').exists()
    blocked = cli('block records original stage', 'transition', '--run-id', run_id, '--event', 'block', '--payload-json', json.dumps({'reason':'User requests filters only'}), '--action-id', 'block')
    assert blocked['state']=='blocked' and blocked['blocked_from']=='awaiting-package-approval'
    cli('cannot inject alternate resume target', 'transition', '--run-id', run_id, '--event', 'resume', '--payload-json', json.dumps({'target':'preparing','validated':True,'reconciliation_hash':'d'*64}), '--action-id', 'resume-injected', expected=2, unchanged=True)
    resumed = cli('resume returns only to original stage', 'resume', '--run-id', run_id, '--action-id', 'resume-normal')
    assert resumed['state']=='awaiting-package-approval'
    assert resumed['candidate_package_hash']==blocked['candidate_package_hash']
    cli('same run init does not reset stage', 'init', '--run-id', run_id, '--kind', 'feature', expected=2, unchanged=True)
    cancelled = cli('explicit cancel is available', 'transition', '--run-id', run_id, '--event', 'cancel', '--payload-json', json.dumps({'authorized':True,'reason':'Explicit test-only user cancellation'}), '--action-id', 'cancel')
    assert cancelled['state']=='cancelled'
    fresh = cli('fresh independent run remains possible', 'init', '--run-id', 'DEV-revised-scope', '--kind', 'feature', unchanged=True)
    assert fresh['state']=='preparing'
    fresh_ready = cli('fresh run can restart shared understanding', 'transition', '--run-id', 'DEV-revised-scope', '--event', 'shared-understanding-ready', '--payload-json', json.dumps({'shared_understanding_hash':'c'*64}), '--action-id', 'new-shared', unchanged=True)
    assert fresh_ready['state']=='awaiting-shared-confirmation'
finally:
    case.doCleanups()
Path(__file__).with_name('transitions-results.json').write_text(json.dumps(out, indent=2, ensure_ascii=False))
for row in out:
    print(f"{row['name']}: rc={row['returncode']} history_unchanged={row['events_unchanged']}")
    if row['stderr']: print(row['stderr'].strip())
print('All assertions passed; disposable repository removed.')
