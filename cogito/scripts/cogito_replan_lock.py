"""Project-wide mutation serialization and authoritative replanning fences."""
from __future__ import annotations
import fcntl
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Callable, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])
from cogito_common import CogitoError
from cogito_events import read_events
from cogito_replan_state import project_replan, TERMINAL

_lock = RLock()
_depth: ContextVar[dict[str, int]] = ContextVar('cogito_project_lock_depth', default={})
_authority: ContextVar[str | None] = ContextVar('cogito_replan_authority', default=None)

@contextmanager
def project_lock(root):
    root = Path(root).resolve()
    key = str(root)
    with _lock:
        depths = _depth.get()
        token = _depth.set({**depths, key: depths.get(key, 0) + 1})
        try:
            if depths.get(key):
                yield
            else:
                path = root / '.cogito' / 'project-mutation.lock'
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('a+') as handle:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    yield
        finally:
            _depth.reset(token)

@contextmanager
def replan_authority(replan_id):
    token = _authority.set(replan_id)
    try:
        yield
    finally:
        _authority.reset(token)

def replans(root):
    for path in sorted((Path(root) / '.cogito' / 'replans').glob('RP-*/events.jsonl')):
        yield project_replan(read_events(path))

def check_run_fence(root, run_id, operation, *, stopping=False):
    from cogito_actions import guard_fixed_action
    guard_fixed_action(root, run_id, operation, stopping=stopping or operation == 'resume_gate')
    if operation == 'run_controlled_check':
        from cogito_path_amendment import pending_from_events
        if pending_from_events(root, run_id):
            raise CogitoError('path amendment review pending; controlled checks are paused')

    for state in replans(root):
        if _authority.get() == state['replan_id']:
            continue
        source, successor = state['source_run_id'], state['successor_run_id']
        if state['state'] == 'completed':
            if run_id == source:
                raise CogitoError('source run was superseded; continue its successor')
            continue
        if state['state'] == 'disposition':
            continue
        if state['state'] == 'abandoned':
            if run_id == successor:
                raise CogitoError('successor belongs to an abandoned replan')
            continue
        if operation == 'approve_package' and run_id != successor:
            raise CogitoError('project approval is fenced by an active replan')
        if run_id == source:
            raise CogitoError(f"run is fenced by {state['replan_id']}; use the replan Gate")
        preparation = {
            'create', 'prepare_package', 'preparation-transition', 'preparation-record',
            'planning_begin', 'planning_review', 'planning_withdraw', 'planning_recover', 'planning-record',
        }
        if run_id == successor and operation in preparation and state['state'] in {'ready-for-handoff', 'handing-off'}:
            raise CogitoError('successor preparation is frozen by approved replan authorization')
        if run_id == successor and operation not in {
            'create', 'prepare_package', 'preparation-transition', 'preparation-record',
            'planning_begin', 'planning_review', 'planning_withdraw', 'planning_recover', 'planning-record',
        }:
            raise CogitoError('successor execution is fenced until approved handoff completes')

def run_mutation(method: F) -> F:
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with project_lock(self.root):
            operation = method.__name__
            event = args[0] if args else kwargs.get('event', kwargs.get('event_type'))
            stopping = operation in {'record', 'transition'} and event in {'block', 'cancel', 'resume'}
            if operation in {'transition', 'record'} and event in {
                'shared-understanding-ready', 'shared-understanding-confirmed', 'boundary-complete',
                'package-ready', 'mini-package-ready',
            }:
                operation = 'preparation-transition' if operation == 'transition' else 'preparation-record'
            if operation == 'record' and event in {'planning-begun', 'planning-reviewed', 'planning-withdrawn'}:
                operation = 'planning-record'
            from cogito_disposition_lock import check_disposition_fence
            check_disposition_fence(self, operation, args, kwargs)
            check_run_fence(self.root, self.run_id, operation, stopping=stopping)
            return method(self, *args, **kwargs)
    return cast(F, wrapped)
