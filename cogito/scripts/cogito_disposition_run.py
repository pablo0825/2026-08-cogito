"""Validated restoration of an original contract after a reviewed withdrawal."""
from copy import deepcopy
from pathlib import Path

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_disposition_snapshot import require_same_product, validate_runtime
from cogito_replan_lock import run_mutation


class DispositionRunMixin:
    def validate_disposition_resume(self, disposition_id):
        from cogito_disposition_store import DispositionStore
        decision = DispositionStore(self.root, disposition_id).load()
        proposal = decision.get('proposal', {})
        withdrawal = proposal.get('withdrawal_authorization', {})
        if (decision['source_run_id'] != self.run_id or proposal.get('action') != 'resume'
                or not isinstance(withdrawal, dict) or withdrawal.get('authorized') is not True):
            raise CogitoError('original-contract resumption requires explicit reviewed withdrawal')
        current = self.load()
        if current['state'] != 'blocked':
            raise CogitoError('only the paused original run can resume; cancelled work needs a follow-up')
        saved = decision['snapshot']
        package = self.approved_package()
        self._validate_policy(package)
        if (self._git('rev-parse', 'HEAD') != saved['delivery']['head']
                or self._git('branch', '--show-current') != saved['delivery']['branch']):
            raise CogitoError('original delivery changed; propose a reviewed restoration task')
        current_index, current_tree = capture_index_and_worktree_trees(self.root)
        runtime_paths = validate_runtime(
            self.root, disposition_id, saved, decision,
            first_tree=saved['delivery']['content_tree'], second_tree=current_tree)
        validate_runtime(
            self.root, disposition_id, saved, decision,
            first_tree=saved['delivery']['index_tree'], second_tree=current_index)
        target = current['blocked_from']
        if target not in self.workflow['resume_targets']:
            raise CogitoError('original phase cannot be resumed')
        human = current.get('human')
        if human or target == 'awaiting-human':
            # Returning to human acceptance is allowed only for the original
            # verified contract and content. Partial repairs need a restoration
            # task; no old checks or automatic close grants are reused for them.
            anchors = [event for event in self._events.read() if event['type'] in {
                'human-review-required', 'human-correction-reviewed', 'human-correction-accepted'}]
            if not anchors:
                raise CogitoError('original human delivery has no verification checkpoint')
            anchor = anchors[-1]
            evidence = [load_json(Path(p)) for p in anchor['payload']['evidence']]
            if not evidence or any(e['effective_contract_hash'] != current['effective_contract_hash'] for e in evidence):
                raise CogitoError('human repair changed the contract; use a restoration follow-up')
            binding = evidence[0]['worktree_binding']['content_tree']
            require_same_product(
                self.root, binding, current_tree, runtime_paths,
                message='human delivery changed after verification; propose a restoration task')
            target = 'post-integration-verification'
        else:
            for before, after in ((saved['delivery']['index_tree'], current_index),
                                  (saved['delivery']['content_tree'], current_tree)):
                require_same_product(
                    self.root, before, after, runtime_paths,
                    message='saved original delivery changed; propose a reviewed restoration task')
            for path, binding in saved['worktrees'].items():
                index, tree = capture_index_and_worktree_trees(Path(path))
                if (self._git_at(Path(path), 'rev-parse', 'HEAD') != binding['head']
                        or (Path(path) != self.root and (index, tree) != (binding['index_tree'], binding['content_tree']))):
                    raise CogitoError('saved worker changed; propose restoration before resuming')
        graph_path = self.root / 'docs/cogito/project-graph.json'
        graph = load_json(graph_path)
        if graph.get('active_run_id') not in {None, self.run_id}:
            raise CogitoError('another run is executing; wait before resuming the original')
        restored = deepcopy(graph)
        restored['active_run_id'] = self.run_id
        for item in package['slices']:
            original = saved['graph']['slices'][item['id']]
            if restored['slices'].get(item['id']) != original:
                raise CogitoError('original Slice metadata changed; restoration needs a new proposal')
        return {'target': target, 'validated': True, 'disposition_id': disposition_id,
                'project_graph_hash': hash_json(restored), 'graph': restored,
                'withdrawal_authorization': deepcopy(withdrawal),
                'carryover_worktrees': deepcopy(saved['worktrees'])}

    @run_mutation
    def disposition_resume(self, disposition_id, action_id):
        from cogito_disposition_lock import current_authority
        from cogito_disposition_store import DispositionStore
        fingerprint = request_fingerprint('disposition-resume', disposition_id=disposition_id)
        replay = self._replay(action_id, 'disposition-resumed', fingerprint)
        if replay is not None:
            return replay
        state = DispositionStore(self.root, disposition_id).load()
        if (current_authority() != disposition_id or state['state'] != 'executing'
                or state['approval']['proposal_hash'] != state['proposal_hash']):
            raise CogitoError('resumption requires the approved disposition Gate')
        payload = self.validate_disposition_resume(disposition_id)
        from cogito_execution_registry import begin_generation
        begin_generation(self.root, self.run_id, disposition_id)
        atomic_write_json(self.root / 'docs/cogito/project-graph.json', payload.pop('graph'))
        return self.record('disposition-resumed', payload, action_id, self._GATE_AUTHORITY,
                           request_hash=fingerprint)
