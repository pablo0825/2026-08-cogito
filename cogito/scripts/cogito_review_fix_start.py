"""Bind a review finding and its amendment through one recoverable operation."""
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, cast

from cogito_actions import fixed_action_authority
from cogito_common import CogitoError, hash_json
from cogito_correction_rules import current_review_finding
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_replan_lock import run_mutation
from cogito_task_finish import (check_fixed_history, load_fixed_request, preflight_store,
                                save_fixed_request)

if TYPE_CHECKING:
    from cogito_run_store import RunStore


def checkout_binding(store):
    state = store.load()
    result = {}
    for task in state['tasks'].values():
        if task.get('worktree'):
            path = Path(task['worktree'])
            result[str(path)] = {'head': store._git_at(path, 'rev-parse', 'HEAD'),
                                'branch': store._git_at(path, 'branch', '--show-current'),
                                'trees': list(capture_index_and_worktree_trees(path))}
    return result


class ReviewFixStartMixin:
    @run_mutation
    def start_review_fix_with_amendment(self, request: Mapping[str, Any], action_id: str):
        store = cast('RunStore', self)
        if (not isinstance(request, dict) or set(request) != {'finding', 'amendment'}
                or not isinstance(request['finding'], dict)
                or set(request['finding']) != {'event_sequence', 'event_hash'}
                or type(request['finding']['event_sequence']) is not int
                or not isinstance(request['finding']['event_hash'], str)
                or not isinstance(request['amendment'], dict)):
            raise CogitoError('review-fix-start input requires exact finding reference and amendment')
        binding = load_fixed_request(store, 'review-fix-start', request, action_id)
        if binding is None:
            state = store.load()
            if state['state'] != 'reviewing' or store.approved_package().get('task_delivery') != 'atomic':
                raise CogitoError('combined review-fix-start requires a reviewing Atomic Development Package')
            current_review_finding(state, store._events.read(), request['finding'])
            if not request['amendment'].get('added_tasks') or request['amendment'].get('path_additions'):
                raise CogitoError('review fix requires in-scope correction tasks, not path additions')
            checkouts = checkout_binding(store)
            for path, data in checkouts.items():
                store._validate_review_content(Path(path), data['trees'][1])
            preview, receipts = preflight_store(store)
            start_action = 'review-fix-bound-start:' + hash_json(action_id)
            preview.enter_review_fix(start_action, finding_reference=request['finding'])
            preview.add_amendment(request['amendment'], action_id)
            binding = save_fixed_request(store, 'review-fix-start', request, action_id,
                {'checkouts': checkouts, 'start_action': start_action}, receipts.steps)
        if not check_fixed_history(store, binding):
            if (store.load()['effective_contract_hash'] != binding['effective_contract_hash']
                    or checkout_binding(store) != binding['prepared']['checkouts']):
                raise CogitoError('review-fix-start checkout or contract changed since preflight')
            with fixed_action_authority(store.root, store.run_id, action_id):
                store.enter_review_fix(binding['prepared']['start_action'], finding_reference=request['finding'])
                store.add_amendment(request['amendment'], action_id)
        return {'operation': 'review-fix-start', 'status': 'started',
                'amendment_id': request['amendment']['id'],
                'task_ids': [t['id'] for t in request['amendment']['added_tasks']],
                'next': store.next_action()}
