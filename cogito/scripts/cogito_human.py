"""Dedicated same-run human feedback gates; execution and evidence stay shared."""
from pathlib import Path
import base64
import hashlib

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, hash_json, load_json
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_evidence_contract import validate_check_evidence
from cogito_gate_validation import derive_review_decision
from cogito_human_rules import (
    validate_feedback, validate_triage, validate_resolution,
    validate_human_budget, can_close_after_fixes,
)
from cogito_replan_lock import run_mutation
from cogito_task_rules import is_active_task


class HumanMixin:
    def _human_budget_spent(self, current):
        return current['counters'].get('human_corrections', 0) >= min(3, current['limits'].get('human_corrections', 3))

    def _human_failed_checks(self, evidence, snapshot, binding):
        """Only an immutable current-run failure can trigger automatic exhaustion."""
        anchor = max(e['sequence'] for e in snapshot.events if e['type'] == 'human-correction-complete')
        failures = []
        for item in evidence:
            path = Path(item.get('evidence_path', '')).resolve()
            ledger = snapshot.state['evidence'].get(str(path))
            if (item.get('passed') is not False or not ledger
                    or (ledger.get('event_sequence') or 0) <= anchor):
                continue
            if not path.is_relative_to((self.run_dir / 'evidence').resolve()):
                continue
            if (load_json(path) == item and hash_json(item) == ledger['evidence_hash']
                    and item.get('effective_contract_hash') == binding['effective_contract_hash']
                    and item.get('head_commit') == binding['head']
                    and item.get('worktree_binding', {}).get('content_tree') == binding['content_tree']):
                failures.append(str(path))
        return failures

    def _human_binding(self):
        state = self.load()
        package = self.approved_package()
        if self._git('branch', '--show-current') != package['delivery_branch']:
            raise CogitoError('human acceptance must use the delivery branch')
        return {'head': self._git('rev-parse', 'HEAD'),
                'content_tree': capture_index_and_worktree_trees(self.root)[1],
                'effective_contract_hash': state['effective_contract_hash']}

    def _human_emit(self, event, payload, action_id, fingerprint, current):
        if 'binding' in payload and self._human_binding() != payload['binding']:
            raise CogitoError('human acceptance delivery changed before recording the event')
        return self.record(event, {**payload, 'human_action_valid': True}, action_id,
                           self._GATE_AUTHORITY, request_hash=fingerprint,
                           expected_previous_hash=current['last_event_hash'])

    def _human_current_evidence(self):
        snapshot = self._events.snapshot()
        events = [e for e in snapshot.events if e['type'] in {
            'human-review-required', 'human-correction-reviewed', 'human-correction-accepted'}]
        if not events:
            raise CogitoError('human acceptance requires a verified delivery')
        evidence = [load_json(Path(p)) for p in events[-1]['payload']['evidence']]
        binding = self._human_binding()
        self._validate_evidence(self.approved_package(), evidence, snapshot=snapshot,
                                phase='post-integration', current_head=binding['head'], validate_supplied=True)
        if not evidence or any(e['worktree_binding'].get('content_tree') != binding['content_tree']
                               for e in evidence):
            raise CogitoError('human acceptance delivery differs from verified content')
        return binding

    @run_mutation
    def human_feedback(self, request, action_id):
        fingerprint = request_fingerprint('human-feedback', request=request)
        replay = self._replay(action_id, {'human-feedback-recorded', 'human-feedback-queued'}, fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        active = {'human-feedback-triage', 'human-correction', 'human-correction-verifying', 'human-correction-reviewing'}
        if current['state'] not in active | {'awaiting-human'}:
            raise CogitoError('feedback requires an active human acceptance cycle')
        feedback = validate_feedback(request)
        if any(e['type'] == 'human-feedback-recorded' and
               e['payload']['feedback']['id'] == feedback['id'] for e in self._events.read()):
            raise CogitoError('feedback ID already exists; use a new batch ID')
        queued = current.get('human', {}).get('pending_feedback', [])
        matching = [f for f in queued if f['id'] == feedback['id']]
        if current['state'] in active:
            if matching:
                raise CogitoError('feedback batch is already queued; use the original action or a new ID')
            return self._human_emit('human-feedback-queued', {'feedback': feedback},
                                    action_id, fingerprint, current)
        if matching and matching[0] != feedback:
            raise CogitoError('queued feedback must retain its exact recorded request')
        binding = self._human_current_evidence()
        payload = {'feedback': feedback, 'binding': binding,
                   'feedback_hash': hash_json({'feedback': feedback, 'binding': binding})}
        return self._human_emit('human-feedback-recorded', payload, action_id, fingerprint, current)

    @run_mutation
    def human_triage(self, request, action_id):
        fingerprint = request_fingerprint('human-triage', request=request)
        replay = self._replay(action_id, 'human-feedback-classified', fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        if current['state'] != 'human-feedback-triage':
            raise CogitoError('classification requires human-feedback-triage')
        triage = validate_triage(request, current['human']['feedback'])
        previous = current['human'].get('triage')
        if previous and previous['route'] == 'change' and triage['route'] != 'change':
            if not triage.get('deferred_item_ids') or not triage.get('split_authorized'):
                raise CogitoError('change feedback cannot become a local fix without an explicit split decision')
            prior_changes = {a['id'] for a in previous['assessments'] if a['disposition'] == 'change'}
            if not prior_changes <= set(triage['deferred_item_ids']):
                raise CogitoError('all previously classified changes must remain in the deferred change batch')
        if self._human_binding() != current['human']['binding']:
            raise CogitoError('delivery changed before feedback classification')
        return self._human_emit('human-feedback-classified', {'triage': triage},
                                action_id, fingerprint, current)

    @run_mutation
    def human_correction_start(self, request, action_id):
        fingerprint = request_fingerprint('human-correction-start', request=request)
        replay = self._replay(action_id, {'human-correction-started', 'human-correction-exhausted'}, fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        if current['state'] not in {'human-feedback-triage', 'human-correction-verifying', 'human-correction-reviewing'}:
            raise CogitoError('human correction cannot start in this state')
        human = current['human']
        if not human.get('triage') or human['triage']['route'] != 'local' or human.get('escalated'):
            raise CogitoError('only a classified local feedback batch may be corrected; use RP or clarify')
        try:
            validate_human_budget(current)
        except CogitoError:
            return self._human_emit('human-correction-exhausted',
                {'reason': 'human correction budget exhausted; report attempts and request a decision'},
                action_id, fingerprint, current)
        if not isinstance(request, dict) or set(request) != {'amendment_id'} or not isinstance(request['amendment_id'], str):
            raise CogitoError('human correction start requires only amendment_id')
        events = self._events.read()
        starts = {e['payload']['amendment_id'] for e in events if e['type'] in {
            'human-correction-started', 'verification-correction-required', 'post-verification-correction-required'}}
        amendments = [e for e in events if e['type'] == 'technical-amendment-added']
        feedback_sequence = max(e['sequence'] for e in events if e['type'] == 'human-feedback-recorded')
        if (not amendments or amendments[-1]['sequence'] < feedback_sequence
                or amendments[-1]['payload']['amendment']['id'] != request['amendment_id']
                or request['amendment_id'] in starts):
            raise CogitoError('human correction requires a fresh amendment for this feedback')
        tasks = amendments[-1]['payload']['amendment'].get('added_tasks', [])
        if not tasks:
            raise CogitoError('human correction requires explicit implementation tasks')
        if any(is_active_task(t) for t in current['tasks'].values()):
            raise CogitoError('finish or stop active tasks before starting a human correction')
        binding = self._human_binding()
        expected = human.get('completion_binding', human['binding'])
        if any(binding[k] != expected[k] for k in ('head', 'content_tree')):
            raise CogitoError('delivery changed outside recorded human correction')
        return self._human_emit('human-correction-started', {
            'amendment_id': request['amendment_id'], 'task_ids': [t['id'] for t in tasks],
            'binding': binding}, action_id, fingerprint, current)

    @run_mutation
    def human_correction_complete(self, request, action_id):
        fingerprint = request_fingerprint('human-correction-complete', request=request)
        replay = self._replay(action_id, 'human-correction-complete', fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        if current['state'] != 'human-correction':
            raise CogitoError('human correction completion requires human-correction')
        if not isinstance(request, dict) or set(request) - {'feedback_id', 'amendment_id', 'commit_id', 'resolved_item_ids', 'summary', 'document_updates'}:
            raise CogitoError('unknown human correction completion fields')
        human = current['human']
        resolution = validate_resolution({k: v for k, v in request.items()
                                           if k not in {'amendment_id', 'commit_id', 'document_updates'}}, human)
        if request.get('amendment_id') != human['amendment_id']:
            raise CogitoError('human correction amendment mismatch')
        ids = set(human['task_ids'])
        if any(current['tasks'][t]['status'] != 'complete' for t in ids):
            raise CogitoError('human correction tasks are incomplete')
        implemented = [r for r in current['agent_results'] if r['task_id'] in ids
                       and r['role'] == 'implementer' and r['status'] == 'complete']
        commit = request.get('commit_id')
        if {r['task_id'] for r in implemented} != ids:
            raise CogitoError('human correction requires recorded Implementer Results')
        package = self.approved_package()
        binding = self._human_binding()
        if commit != binding['head']:
            raise CogitoError('human correction must complete at current delivery HEAD')
        payload = {'amendment_id': human['amendment_id'], 'commit_id': commit,
                   'resolution': resolution, 'binding': binding}
        updates = request.get('document_updates', [])
        if not isinstance(updates, list):
            raise CogitoError('document_updates must be a list')
        allowed_documents = {sl[key]['path'] for sl in package['slices'] for key in ('spec', 'plan')}
        declared = set()
        documents = []
        for update in updates:
            if (not isinstance(update, dict) or set(update) != {'path', 'reason'}
                    or not isinstance(update['path'], str) or update['path'] not in allowed_documents
                    or update['path'] in declared or not isinstance(update['reason'], str) or not update['reason'].strip()):
                raise CogitoError('document update must uniquely name a Package Spec/Plan with its local adjustment reason')
            path = update['path']
            declared.add(path)
            before = self._git_repo.read_blob(human['start_binding']['content_tree'], path)
            after = self._git_repo.read_blob(binding['content_tree'], path)
            documents.append({**update, 'before_hash': hashlib.sha256(before).hexdigest(),
                              'after_hash': hashlib.sha256(after).hexdigest(),
                              'before_base64': base64.b64encode(before).decode(),
                              'after_base64': base64.b64encode(after).decode()})
        changed = set(filter(None, self._git('diff', '--name-only', '--no-renames', '-z',
                                            human['start_binding']['content_tree'], binding['content_tree'], '--').split('\0')))
        if changed & allowed_documents != declared:
            raise CogitoError('declare every changed Spec/Plan as a local document update')
        payload['document_updates'] = documents
        if package['kind'] == 'maintenance':
            last = implemented[-1]
            task = current['tasks'][last['task_id']]
            index, tree = capture_index_and_worktree_trees(self.root)
            if (tree != task.get('maintenance_end_tree') or
                    index != task.get('maintenance_end_index_tree')):
                raise CogitoError('human correction changed after the last Implementer Result')
            payload.update(self._maintenance_correction_snapshot(package, self._events.read(), commit))
        else:
            last_head = implemented[-1]['head_commit']
            if commit != last_head:
                self._git('merge-base', '--is-ancestor', last_head, commit)
                after_result = set(filter(None, self._git('diff', '--name-only', '--no-renames', '-z',
                                                          last_head, commit, '--').split('\0')))
                if not declared or not after_result or after_result - declared:
                    raise CogitoError('only declared Spec/Plan updates may follow the last Implementer Result')
            dirty = set(filter(None, self._git('diff', '--name-only', '--no-renames', '-z',
                                              commit, binding['content_tree'], '--').split('\0')))
            controls = {current['package_path'], 'docs/cogito/project-graph.json'}
            if dirty - controls:
                raise CogitoError('human correction has uncommitted content after Implementer Result')
            if f"Cogito-Amendment: {human['amendment_id']}" not in self._git('show', '-s', '--format=%B', commit).splitlines():
                raise CogitoError('human correction commit is missing its Cogito-Amendment trailer')
        return self._human_emit('human-correction-complete', payload, action_id, fingerprint, current)

    @run_mutation
    def human_verify(self, evidence, action_id):
        fingerprint = request_fingerprint('human-verify', evidence=evidence)
        replay = self._replay(action_id, {'human-correction-verified', 'human-correction-exhausted'}, fingerprint)
        if replay is not None:
            return replay
        snapshot = self._events.snapshot()
        current = snapshot.state
        if current['state'] != 'human-correction-verifying':
            raise CogitoError('human verification requires human-correction-verifying')
        for item in evidence:
            validate_check_evidence(item)
        binding = self._human_binding()
        if binding != current['human']['completion_binding']:
            raise CogitoError('human correction content changed after completion')
        if self._human_budget_spent(current):
            failures = self._human_failed_checks(evidence, snapshot, binding)
            if failures:
                return self._human_emit('human-correction-exhausted',
                    {'reason': 'third human correction failed controlled checks; report attempts and request a decision',
                     'failed_evidence': failures}, action_id, fingerprint, current)
        self._validate_evidence(self.approved_package(), evidence, snapshot=snapshot,
                                phase='post-integration', current_head=binding['head'], validate_supplied=True)
        if not evidence or any(e['worktree_binding']['content_tree'] != binding['content_tree'] for e in evidence):
            raise CogitoError('human correction evidence differs from delivery content')
        return self._human_emit('human-correction-verified',
            {'evidence': [e['evidence_path'] for e in evidence], 'binding': binding,
             'delivery_head': binding['head']}, action_id, fingerprint, current)

    @run_mutation
    def human_review(self, action_id):
        fingerprint = request_fingerprint('human-review')
        replay = self._replay(action_id, {'human-correction-reviewed', 'human-correction-accepted', 'human-correction-exhausted'}, fingerprint)
        if replay is not None:
            return replay
        snapshot = self._events.snapshot()
        current = snapshot.state
        if current['state'] != 'human-correction-reviewing':
            raise CogitoError('human review requires human-correction-reviewing')
        human = current['human']
        cycle = max(e['sequence'] for e in snapshot.events if e['type'] == 'human-correction-verified')
        cohort = {**current, 'tasks': {t: current['tasks'][t] for t in human['cohort_task_ids']},
                  'agent_results': [e['payload']['result'] for e in snapshot.events
                                    if e['type'] == 'agent-result-recorded' and e['sequence'] > cycle]}
        # Human-returned changes receive independent review even for a Mini run.
        try:
            decision = derive_review_decision(self.approved_package(), cohort)
        except CogitoError:
            latest = {r['task_id']: r for r in cohort['agent_results'] if r['role'] == 'reviewer'}
            if self._human_budget_spent(current) and any(
                    r['status'] == 'needs-fix' and r['task_id'] in cohort['tasks'] for r in latest.values()):
                return self._human_emit('human-correction-exhausted',
                    {'reason': 'third human correction failed independent review; report findings and request a decision'},
                    action_id, fingerprint, current)
            raise
        binding = self._human_binding()
        if binding != human['verification']['binding']:
            raise CogitoError('human correction changed after verification')
        self._validate_review_content(self.root, binding['content_tree'])
        close = can_close_after_fixes(human)
        payload = {**decision, 'binding': binding, 'delivery_head': binding['head'],
                   'feedback_hash': human['feedback_hash'], 'conditional': close,
                   'evidence': human['verification']['evidence']}
        return self._human_emit('human-correction-accepted' if close else 'human-correction-reviewed',
                                payload, action_id, fingerprint, current)

    @run_mutation
    def human_escalate(self, request, action_id):
        fingerprint = request_fingerprint('human-escalate', request=request)
        replay = self._replay(action_id, 'human-feedback-escalated', fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        if current['state'] not in {'human-feedback-triage', 'human-correction',
                                    'human-correction-verifying', 'human-correction-reviewing'}:
            raise CogitoError('escalation requires an active human feedback cycle')
        if (not isinstance(request, dict) or set(request) != {'reason'} or not isinstance(request['reason'], str)
                or not request['reason'].strip()):
            raise CogitoError('human escalation requires a reason')
        return self._human_emit('human-feedback-escalated', request, action_id, fingerprint, current)
