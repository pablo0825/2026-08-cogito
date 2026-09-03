"""Independent Maintenance probes; run from repository root."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = ['cogito/scripts', 'cogito/tests']
from test_staged_maintenance import StagedMaintenanceTests
from cogito_test_support import git, init_repo, package
from cogito_run_store import RunStore
from cogito_common import CogitoError

case = StagedMaintenanceTests()
try:
    with patch.object(RunStore, 'update_task', lambda self, *args: self.load()):
        repo, store, base = case.fixture()
    (repo / 'note.txt').write_text('unclaimed before lease\n')
    before = store.events_path.read_bytes()
    index = (repo / '.git/index').read_bytes()
    try:
        store.update_task('T-1', 'leased', 'worker-1')
    except CogitoError as error:
        print('prelease_dirty_rejected:', str(error))
    else:
        raise AssertionError('prelease dirty accepted')
    assert before == store.events_path.read_bytes()
    assert index == (repo / '.git/index').read_bytes()
finally:
    case.doCleanups()

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    repo, child = root / 'main', root / 'child'
    repo.mkdir()
    child.mkdir()
    init_repo(repo)
    init_repo(child)
    (child / 'note.txt').write_text('before\n')
    git(child, 'add', '.')
    git(child, 'commit', '-qm', 'child')
    (repo / '.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n')
    git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(child), 'module')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'baseline')
    base = git(repo, 'rev-parse', 'HEAD')
    draft = package('maintenance')
    draft.update({
        'baseline_commit': base,
        'approved_paths': ['module'],
        'execution_dag': {'tasks': [{'id': 'T-1', 'paths': ['module']}], 'edges': []},
    })
    store = RunStore(repo, draft['run_id'])
    store.create('maintenance')
    store.prepare_package(draft)
    store.approve_package(draft)
    store.start_gate()
    store.update_task('T-1', 'leased', 'worker-1')
    store.update_task('T-1', 'running', 'worker-1')
    (repo / 'module/note.txt').write_text('dirty module\n')
    before = store.events_path.read_bytes()
    index = (repo / '.git/index').read_bytes()
    result = StagedMaintenanceTests.result(store, base, [])
    try:
        store.submit_agent_result(result)
    except CogitoError as error:
        print('submodule_dirty_rejected:', str(error))
    else:
        raise AssertionError('submodule dirty accepted')
    assert before == store.events_path.read_bytes()
    assert index == (repo / '.git/index').read_bytes()
    print('both_probe_event_and_index_bytes_unchanged: true')
