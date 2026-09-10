"""Bounded, advisory operation bundles using existing selectors and validators."""
from pathlib import Path
from datetime import datetime
from copy import deepcopy

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, hash_json, load_json
from cogito_gate_validation import derive_review_decision, verification_checks
from cogito_run_queries import operation_hint
from cogito_task_finish import collect_check_candidates, unfinished_check_actions

MAX_ITEMS = 50


def _task_context(store, package, task):
    """Copy only dispatch/review context; never synthesize task responsibility."""
    context = {key: deepcopy(task[key]) for key in
               ('id', 'slice_id', 'responsibility', 'paths', 'check_ids', 'depends_on') if key in task}
    slices = {item['id']: item for item in package.get('slices', [])}
    owner = slices.get(task.get('slice_id'))
    context['documents'] = {key: deepcopy(owner[key]) for key in ('spec', 'plan') if owner and key in owner}
    if package.get('shared_understanding', {}).get('path'):
        context['documents']['shared_understanding'] = deepcopy(package['shared_understanding'])
    if package['kind'] in {'maintenance', 'documentation'}:
        worktree, branch = store.root, package['delivery_branch']
    elif owner:
        worktree = (store.root / owner['worker']['worktree']).resolve()
        branch = owner['worker']['branch']
    else:
        raise CogitoError('task has no owning Slice')
    context.update(worktree=str(worktree), branch=branch)
    return context


def dispatch_hints(store, state, task_ids):
    package = store._approved_package_from_state(state)
    contexts = []
    for task_id in task_ids:
        context = _task_context(store, package, state['tasks'][task_id])
        hint = operation_hint(store.root, store.run_id, 'task',
            ['--task-id', task_id, '--status', 'leased', '--agent-id', '<agent-id>'])
        context['operations'] = [hint]
        contexts.append(context)
    return {'dispatch_tasks': contexts,
            'dispatch_note': 'Context is advisory, not a lease or worktree readiness check. '
                'Use the real executor identity; after leasing, register the executor before task running. '
                'Execute one lease then query next again; Gate revalidates current scope and checkout.'}


def reviewer_hints(store, state):
    """Draft immutable references, leaving every reviewer judgment unfilled."""
    package = store._approved_package_from_state(state)
    events = store._events.read()
    cycle = max((e['sequence'] for e in events if e['type'] == 'verification-passed'), default=0)
    current = [e['payload']['result'] for e in events
               if e['type'] == 'agent-result-recorded' and e['sequence'] > cycle]
    contexts = []
    for task in state['tasks'].values():
        if task.get('status') != 'verified':
            continue
        try:
            derive_review_decision(package, {**state, 'tasks': {task['id']: task}, 'agent_results': current})
        except CogitoError:
            pass
        else:
            continue
        context = _task_context(store, package, task)
        context.update(worktree=task.get('worktree'), branch=task.get('branch'))
        implemented = [r for r in state['agent_results'] if r['task_id'] == task['id']
                       and r['role'] == 'implementer' and r['status'] == 'complete']
        context['operations'] = []
        if not implemented or not task.get('agent_id') or not task.get('worktree'):
            context['blockers'] = ['recorded implementation or lease is missing; cannot draft review references']
        else:
            result = implemented[-1]
            draft = {'schema_version': '3.0', 'run_id': store.run_id, 'task_id': task['id'],
                     'role': 'reviewer', 'reviewed_implementer': task['agent_id'],
                     'base_commit': result['base_commit'], 'head_commit': result['head_commit']}
            if package['kind'] == 'maintenance':
                try:
                    draft['head_commit'] = store._git_at(Path(task['worktree']), 'rev-parse', 'HEAD')
                except (CogitoError, OSError) as exc:
                    context['blockers'] = [_reason(exc)]
                    contexts.append(context)
                    continue
            context['operations'] = [operation_hint(store.root, store.run_id, 'agent-result',
                input_value=draft, required_inputs=['agent_id', 'status', 'changed_paths',
                                                   'evidence', 'risks', 'requested_transition'])]
        contexts.append(context)
    return {'review_tasks': contexts,
            'review_note': 'Fill the draft only after independent review. Do not infer approval from these references. '
                'Gate revalidates the implementation range and current verified content when recording the Result. '
                'After recording, query next again; when all reviews are complete, use the existing review-approved transition.'}


def _reason(exc):
    return str(exc)[:600]


def _run_check(store, check_id, worktree, action_id='<new-action-id>'):
    return operation_hint(store.root, store.run_id, 'run-check',
                          ['--check-id', check_id, '--worktree', str(worktree)], action_id=action_id)


def _delivery_candidates(store, state, ids):
    """Atomic post-checks may retain exact content-equivalent Worker evidence.

    Pick the latest attempt across relevant checkouts before validation, never
    search backwards for a passing record. Wave selection stays per-checkout.
    """
    checkouts = {str(store.root)} | {str(Path(t['worktree']).resolve())
        for t in state['tasks'].values() if t.get('worktree')}
    latest = {}
    for checkout in sorted(checkouts):
        for key, path in collect_check_candidates(store, ids, checkout).items():
            started = datetime.fromisoformat(load_json(Path(path))['started_at'])
            prior = latest.get(key)
            if prior and prior[0] == started and prior[1] != path:
                raise CogitoError('ambiguous controlled check attempts: ' + key)
            if prior is None or prior[0] < started:
                latest[key] = (started, path)
    return {key: value[1] for key, value in latest.items()}


def verification_hints(store, state):
    snapshot = store._events.snapshot()
    package = store._approved_package_from_state(state)
    effective = store.effective_package()
    post = state['state'] == 'post-integration-verification'
    phase = 'post-integration' if post else 'implementation'
    atomic = package.get('task_delivery') == 'atomic'
    groups = {}
    if post:
        groups[str(store.root)] = list(verification_checks(effective, phase))
    elif atomic:
        # Earlier Task receipts remain historical. The last Task on each
        # checkout supplies the checks for that checkout's current contents.
        for result in state['agent_results']:
            task = state['tasks'].get(result.get('task_id'), {})
            if result.get('role') == 'implementer' and task.get('status') in {'complete', 'verified'}:
                groups[task['worktree']] = list(task['check_ids'])
    else:
        groups = {task['worktree']: list(verification_checks(effective, phase))
                  for task in state['tasks'].values() if task.get('status') == 'complete'}
    output = {'operations': [], 'eligible_evidence': [], 'missing_checks': [], 'stale_checks': []}
    if not groups or sum(map(len, groups.values())) > MAX_ITEMS:
        output['blockers'] = ['candidate_scope_unavailable: no checkout or more than 50 required candidates']
        return output
    if not any(groups.values()):
        output['blockers'] = ['optional_check_selection_required: choose at least one applicable controlled check as content evidence, then explicitly supply its evidence to verify/post-verify; this hint does not make all optional checks required']
        return output
    evidence = []
    try:
        for worktree, ids in groups.items():
            candidates = (_delivery_candidates(store, state, ids) if atomic and post
                          else collect_check_candidates(store, ids, worktree))
            for check_id in ids:
                identity = {'check_id': check_id, 'worktree': worktree}
                path = candidates.get(check_id)
                if path is None:
                    output['missing_checks'].append(identity)
                    output['operations'].append(_run_check(store, check_id, worktree))
                    continue
                item = load_json(Path(path))
                try:
                    # Atomic implementation validates each record independently;
                    # the full wave below binds it to its current checkout.
                    store._validate_evidence(package, [item], snapshot=snapshot, phase=phase,
                        current_head=store._git('rev-parse', 'HEAD') if post else None,
                        read_only=True, candidate_only=True)
                    if item['passed'] is not True:
                        raise CogitoError('latest_check_failed')
                    if atomic and not post:
                        tree = store._require_atomic_clean(Path(worktree),
                            store._git_at(Path(worktree), 'rev-parse', 'HEAD'), state, read_only=True)
                        if item['worktree_binding'].get('content_tree') != tree:
                            raise CogitoError('stale_content_tree')
                    elif not post:
                        from cogito_evidence_binding import inspect_atomic_content
                        tree, _ = inspect_atomic_content(Path(worktree),
                            store._git_at(Path(worktree), 'rev-parse', 'HEAD'))
                        if item['worktree_binding'].get('content_tree') != tree:
                            raise CogitoError('stale_content_tree')
                except (CogitoError, OSError, KeyError, ValueError) as exc:
                    output['stale_checks'].append({**identity, 'reason': _reason(exc)})
                    output['operations'].append(_run_check(store, check_id, worktree))
                    continue
                evidence.append(item)
        if output['missing_checks'] or output['stale_checks']:
            return output
        if atomic and not post:
            store._validate_atomic_wave(evidence, snapshot, read_only=True)
        else:
            store._validate_evidence(package, evidence, snapshot=snapshot, phase=phase,
                current_head=store._git('rev-parse', 'HEAD') if post else None, read_only=True)
        output['eligible_evidence'] = [item['evidence_path'] for item in evidence]
        arguments = [arg for item in evidence for arg in ('--evidence', item['evidence_path'])]
        hint = operation_hint(store.root, store.run_id, 'post-verify' if post else 'verify',
                              arguments, action_id='<new-action-id>')
        if post:
            hint['judgment_required'] = 'Decide whether reviewer escalation is required before submitting.'
        output['operations'] = [hint]
    except (CogitoError, OSError, KeyError, ValueError) as exc:
        output['blockers'] = [_reason(exc)]
    return output


def check_recovery_hints(store, state):
    from cogito_check_retry import prepare_link
    from cogito_task_finish import PreflightEvents
    snapshot = store._events.snapshot()
    unfinished = unfinished_check_actions(store, snapshot)
    requests = [load_json(p) for p in sorted((store.run_dir / 'check-actions').glob('*/request.json'))
                if not (p.parent / 'started.json').exists()]
    if len(unfinished) + len(requests) > MAX_ITEMS:
        return {'check_recovery': [{'category': 'scope_too_large', 'reason': 'Inspect attempts; over 50 pending requests.'}]}
    contract = store.effective_package()
    checkouts = {str(store.root)} | {t['worktree'] for t in state['tasks'].values() if t.get('worktree')}
    operations, recoveries = [], []
    for request in [*unfinished, *requests]:
        action = request['action_id']
        if request in requests and any(e['type'] == 'check-evidence-recorded'
                and e.get('request_hash') == request['request_hash'] for e in snapshot.events):
            continue  # A never-started request cannot invalidate a completed check.
        matches = [(c['id'], w) for c in contract['checks'] for w in checkouts
                   if request_fingerprint('run-check', check_id=c['id'], worktree=str(Path(w).resolve()))
                   == request['request_hash']]
        row = {'action_id': action, 'category': 'unknown_outcome'}
        if len(matches) != 1:
            if request in requests:
                continue  # No marker means no execution to resolve, even after contract drift.
            row['reason'] = 'Original check/checkout cannot be uniquely reconstructed; obtain the original request.'
            recoveries.append(row)
            continue
        check_id, worktree = matches[0]
        row.update(check_id=check_id, worktree=worktree)
        if request in requests:
            from cogito_runner import validate_check_target
            try:
                validate_check_target(contract, state, check_id, Path(worktree).resolve(), store.root)
            except CogitoError:
                continue  # Never-started requests are not execution blockers.
        record_id = f"{check_id}-{hash_json({'action_id': action})[:16]}"
        if request in requests or (store.run_dir / 'evidence' / f'{record_id}.json').exists():
            row['category'] = 'not_started' if request in requests else 'published_evidence'
            row['reason'] = 'Resend exact request; Gate revalidates phase, binding and evidence.'
            operations.append(_run_check(store, check_id, worktree, action))
        else:
            links = [e['payload']['check_retry'] for e in snapshot.events if e['type'] == 'transient-retry'
                     and e['payload'].get('check_retry', {}).get('source_action_id') == action]
            completed = {e.get('action_id') for e in snapshot.events if e['type'] == 'check-evidence-recorded'}
            if links and links[-1]['replacement_action_id'] not in completed:
                row.update(category='bound_replacement', replacement_action_id=links[-1]['replacement_action_id'])
                # A started replacement with unknown outcome must not be rerun.
                replacement = links[-1]['replacement_action_id']
                if not (store.run_dir / 'check-actions' / hash_json(replacement) / 'started.json').exists():
                    operations.append(_run_check(store, check_id, worktree, replacement))
            else:
                try:
                    link = prepare_link(store, action, '<replacement-action-id>', read_only=True)
                    PreflightEvents(store).append({'type': 'transient-retry',
                        'payload': {'reason': 'retry proven pre-execution failure', 'check_retry': link}})
                    row.update(category='proven_pre_execution_failure',
                               action_rule='Use distinct new retry and replacement IDs; preserve source ID.',
                               remaining_retries=state['limits']['transient_retries'] - state['counters'].get('transient_retries', 0))
                    operations.append(operation_hint(store.root, store.run_id, 'retry',
                        ['--kind', 'transient', '--reason', 'retry proven pre-execution failure',
                         '--check-action-id', action, '--replacement-action-id', '<replacement-action-id>'],
                        action_id='<retry-action-id>'))
                except (CogitoError, OSError, KeyError, ValueError) as exc:
                    row['reason'] = _reason(exc)
        recoveries.append(row)
    return {'check_recovery': recoveries, 'operations': operations} if recoveries else {}


def integration_hints(store, state):
    from cogito_integration_rules import derive_integration_decision
    from cogito_delivery_scope import validate_committed_scope
    package = store._approved_package_from_state(state)
    if package.get('task_delivery') != 'atomic':
        return {}
    choices = []
    for item in package['slices']:
        slice_id = item['id']
        tasks = [t for t in state['tasks'].values() if t.get('slice_id') == slice_id]
        if not tasks or not all(t['status'] == 'reviewed' for t in tasks):
            continue
        row = {'slice_id': slice_id, 'operations': []}
        try:
            decision = derive_integration_decision(state, store._events.read(), slice_id)
            latest = {r['task_id']: r for r in state['agent_results']
                      if r.get('task_id') in decision.task_ids and r.get('role') == 'implementer'
                      and r.get('status') == 'complete'}
            if set(latest) != set(decision.task_ids):
                raise CogitoError('atomic integration requires recorded Task Results')
            results = [r for r in state['agent_results'] if r.get('task_id') in latest
                       and r is latest[r['task_id']]]
            tip = results[-1]['head_commit']
            head, branch = store._git('rev-parse', 'HEAD'), store._git('branch', '--show-current')
            row.update(delivery_head=head, delivery_branch=branch, source_heads=list(decision.source_heads),
                       source_tip=tip, previous_delivery_head=decision.previous_delivery_head)
            if branch != package['delivery_branch']:
                raise CogitoError('wrong_delivery_branch')
            if head not in {decision.previous_delivery_head, tip}:
                raise CogitoError('delivery_head_drift: inspect the actual merge through the normal integration procedure')
            for source in decision.source_heads:
                store._git('merge-base', '--is-ancestor', source, tip)
            try:
                store._git('merge-base', '--is-ancestor', decision.previous_delivery_head, tip)
            except CogitoError as exc:
                raise CogitoError('non_fast_forward: this hint supports fast-forward only; use reviewed merge/conflict handling, then the existing integrate validator') from exc
            validate_committed_scope(package, decision.previous_delivery_head, tip, store._git,
                {'docs/cogito/project-graph.json'}, store._git_repo.read_blob,
                graph_hash=state['project_graph_hash'], approved_paths=store.effective_package()['approved_paths'])
            store._require_atomic_clean(store.root, head, state, read_only=True)
            row.update(mode='fast-forward', expected_head=tip, forbidden=['cherry-pick'])
            if head != tip:
                row['operations'].append({'operation': 'git-merge', 'cwd': str(store.root),
                    'argv': ['git', '-C', str(store.root), 'merge', '--ff-only', tip]})
            row['operations'].append(operation_hint(store.root, store.run_id, 'integrate',
                ['--slice-id', slice_id, '--commit-id', tip], action_id='<new-action-id>'))
        except (CogitoError, OSError, KeyError, ValueError) as exc:
            row['blockers'] = [_reason(exc)]
        choices.append(row)
    if len(choices) > MAX_ITEMS:
        return {'blockers': ['integration_scope_too_large: select a Slice explicitly']}
    return {'integration_choices': choices, 'integration_rule': 'Execute ONE choice, then query next again. Mutation revalidates current facts.'}


def accepted_hints(store, state):
    from cogito_cleanup import assess_cleanup
    output = {'cleanup': assess_cleanup(store)}
    try:
        finals = [e for e in store._events.read() if e['type'] == 'finalization-complete']
        if len(finals) != 1:
            raise CogitoError('original_finalize_request_unavailable')
        event = finals[0]
        payload = event['payload']
        request = {key: payload[key] for key in ('result_path', 'project_graph_path', 'final_commit')}
        if not event.get('action_id') or request_fingerprint('finalize', **request) != event.get('request_hash'):
            raise CogitoError('original_finalize_fingerprint_unavailable: obtain original literal arguments and action ID; do not invent a new action')
        output['operations'] = [operation_hint(store.root, store.run_id, 'finalize',
            ['--result', request['result_path'], '--project-graph', request['project_graph_path'],
             '--final-commit', request['final_commit']], action_id=event['action_id'])]
    except (CogitoError, KeyError, TypeError, ValueError) as exc:
        output['blockers'] = [_reason(exc)]
    return output
