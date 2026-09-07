"""Internal authority and execution fences for pending outcome decisions."""
from contextlib import contextmanager
from contextvars import ContextVar

from cogito_common import CogitoError

_authority = ContextVar('cogito_disposition_authority', default=None)


@contextmanager
def disposition_authority(disposition_id):
    token = _authority.set(disposition_id)
    try:
        yield
    finally:
        _authority.reset(token)


def current_authority():
    return _authority.get()


def check_disposition_fence(store, operation, args=(), kwargs=None):
    from cogito_disposition_scope import dispositions, check_package
    kwargs = kwargs or {}
    entries = list(dispositions(store.root))
    if not entries:
        return
    event = args[0] if args else kwargs.get('event', kwargs.get('event_type'))
    if operation == 'transition' and event == 'cancel':
        return  # Dedicated cancellation below validates/replays its owning DP.
    for state in entries:
        if _authority.get() != state['disposition_id'] and store.run_id in {*state.get('retired_followup_run_ids', []), state.get('successor_run_id')}:
            raise CogitoError(f"run was retired by disposition {state['disposition_id']}")
        if state['state'] == 'completed' or _authority.get() == state['disposition_id']:
            continue
        sources = {state['source_run_id'], state.get('successor_run_id')}
        if store.run_id in sources:
            raise CogitoError(f"run is fenced by {state['disposition_id']}; use the disposition Gate")
    # Preparation remains possible while a plan is awaiting approval. Actual
    # execution/approval rechecks durable holds, including semantic dependencies.
    if operation in {'create', 'prepare_package', 'planning_begin', 'planning_review',
                     'planning_withdraw', 'planning_recover', 'preparation-transition',
                     'preparation-record', 'planning-record'}:
        return
    if operation in {'transition', 'record'} and event == 'block':
        return
    if operation == 'approve_package':
        package = args[0] if args else kwargs['draft']
    else:
        if not store.events_path.exists():
            return
        state = store._events.project()
        if not state.get('package_path'):
            return
        package = store.approved_package()
    extra_paths = []
    if store.events_path.exists():
        for amendment in store._events.project().get('amendments', []):
            value = amendment.get('amendment', amendment)
            extra_paths.extend(value.get('path_fixes', []))
            for task in value.get('added_tasks', []):
                extra_paths.extend(task.get('paths', []))
            for addition in value.get('path_additions', []):
                extra_paths.extend(addition['paths'])
    if operation == 'add_amendment':
        amendment = args[0] if args else kwargs['amendment']
        extra_paths.extend(amendment.get('path_fixes', []))
        for task in amendment.get('added_tasks', []):
            extra_paths.extend(task.get('paths', []))
        for addition in amendment.get('path_additions', []):
            extra_paths.extend(addition['paths'])
    check_package(store.root, package, store.run_id, skip_disposition_id=_authority.get(), extra_paths=extra_paths)
