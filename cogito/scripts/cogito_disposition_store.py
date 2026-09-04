"""Journaled, independently reviewed disposition of stopped run artifacts."""
from __future__ import annotations
import copy
import re
from functools import wraps
from pathlib import Path
from cogito_actions import request_fingerprint, require_same_request
from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_events import append_event, read_events
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_replan_lock import project_lock, replan_authority, replans
from cogito_run_store import RunStore
from cogito_disposition_state import project_disposition, validate_proposal, validate_review
from cogito_disposition_snapshot import capture_runtime, require_same_product, validate_runtime


def mutation(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        from cogito_disposition_lock import disposition_authority
        with project_lock(self.root), disposition_authority(self.disposition_id):
            events = read_events(self.events_path)
            rp = project_disposition(events).get('replan_id') if events else kwargs.get('replan_id')
            with replan_authority(rp):
                try:
                    return method(self, *args, **kwargs)
                except OSError as exc:
                    raise CogitoError('disposition storage failed; inspect history and retry the same action_id: '+str(exc)) from exc
    return call


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise CogitoError(label+' must be nonempty text')


class DispositionStore:
    def __init__(self, root, disposition_id):
        if not isinstance(disposition_id, str) or not re.fullmatch(r'DP-[A-Za-z0-9._-]+', disposition_id):
            raise CogitoError('disposition_id must be a safe DP-* identifier')
        self.root = Path(root).resolve()
        self.disposition_id = disposition_id
        self.directory = self.root/'.cogito/dispositions'/disposition_id
        if self.directory.resolve() != self.directory:
            raise CogitoError('disposition storage must not traverse symlinks')
        self.events_path = self.directory/'events.jsonl'

    def load(self):
        state = project_disposition(read_events(self.events_path))
        atomic_write_json(self.directory/'state.json', state)
        return state

    def source(self):
        return RunStore(self.root, self.load()['source_run_id'])

    def _replay(self, action_id, operation, request):
        nonempty(action_id, 'action_id')
        matches = [e for e in read_events(self.events_path) if e.get('action_id') == action_id]
        if matches:
            require_same_request(matches[0], request_fingerprint(operation, **request), action_id)
            return self.load()
        return None

    def _emit(self, kind, payload, action_id, operation, request):
        events = read_events(self.events_path)
        event = dict(type=kind, payload=payload, action_id=action_id,
                     request_hash=request_fingerprint(operation, **request))
        project_disposition([*events, event])
        append_event(self.events_path, event, events[-1]['event_hash'] if events else '0'*64)
        return self.load()

    @mutation
    def begin(self, source_run_id, reason, action_id, replan_id=None, cancel_source=None):
        request = dict(source_run_id=source_run_id, reason=reason, replan_id=replan_id, cancel_source=(not replan_id if cancel_source is None else cancel_source))
        if type(request['cancel_source']) is not bool:
            raise CogitoError('cancel_source must be boolean')
        replay = self._replay(action_id, 'begin', request)
        if not replay:
            if self.events_path.exists(): raise CogitoError('disposition already exists')
            nonempty(reason, 'reason')
            source = RunStore(self.root, source_run_id)
            current = source.load()
            if current['state'] in {'cancelled','superseded'} and not replan_id:
                raise CogitoError('source is already terminal; follow its existing disposition')
            for path in (self.root/'.cogito/dispositions').glob('DP-*/events.jsonl'):
                other = project_disposition(read_events(path))
                if other['state'] != 'completed' and other['source_run_id'] == source_run_id:
                    raise CogitoError('source already has an unresolved disposition')
            from cogito_replan_state import TERMINAL
            active = [rp for rp in replans(self.root) if rp['state'] not in TERMINAL]
            if active and not any(rp['replan_id'] == replan_id and rp['source_run_id'] == source_run_id for rp in active):
                raise CogitoError('use the active source replan when creating its disposition')
            run_ids = [source_run_id]
            if replan_id:
                from cogito_replan_store import ReplanStore
                rp = ReplanStore(self.root, replan_id).load()
                if rp['source_run_id'] != source_run_id or rp['state'] == 'abandoned':
                    raise CogitoError('replan does not own this source')
                successor = RunStore(self.root, rp['successor_run_id'])
                if successor.events_path.exists(): run_ids.append(successor.run_id)
            graph_path = self.root/'docs/cogito/project-graph.json'
            graph = load_json(graph_path) if graph_path.exists() else None
            if graph and graph.get('active_run_id') not in {None, *run_ids}:
                raise CogitoError('another run owns Project Graph')
            # Refuse before writing the fence if actual running workers lack handles.
            from cogito_execution_registry import snapshot
            for run_id in run_ids:
                current_run = RunStore(self.root, run_id).load()
                active_agents = {t['agent_id'] for t in current_run['tasks'].values() if t['status'] in {'leased','running'}}
                if not active_agents <= set(snapshot(self.root,run_id)['entries']):
                    raise CogitoError('register every active executor before requesting disposition')
            self._emit('disposition-created', dict(**request, disposition_id=self.disposition_id,
                source_state=current.get('blocked_from') if current['state']=='blocked' else current['state'], run_ids=run_ids, successor_run_id=(run_ids[1] if len(run_ids)>1 else None), graph_before=graph), action_id,'begin',request)
        if self.load()['state'] == 'stopping': self._request_stop()
        return self.load()

    def _request_stop(self):
        from cogito_execution_registry import request_stop
        for run_id in self.load()['run_ids']:
            run = RunStore(self.root, run_id)
            if run.load()['state'] not in {'blocked','accepted','cancelled','superseded'}:
                run.transition('block', {'reason':'disposition '+self.disposition_id}, 'disposition-block:'+self.disposition_id)
            request_stop(self.root,run_id,deadline_seconds=60)

    def _capture(self, extra_runs=()):
        runs, worktrees = {}, {}
        for run_id in dict.fromkeys([*self.load()['run_ids'], *extra_runs]):
            run = RunStore(self.root,run_id)
            current = run.load()
            runs[run_id] = dict(state=current['state'],event_hash=current['last_event_hash'],
                tasks=current['tasks'],package_hash=current.get('package_hash'))
            for task in current['tasks'].values():
                if task.get('worktree'):
                    path = Path(task['worktree']).resolve()
                    try: path.relative_to(self.root)
                    except ValueError as exc: raise CogitoError('worker worktree escapes project') from exc
                    index, tree = capture_index_and_worktree_trees(path)
                    worktrees[str(path)] = dict(head=run._git_at(path,'rev-parse','HEAD'),
                        branch=run._git_at(path,'branch','--show-current'),index_tree=index,content_tree=tree)
        source = self.source(); current = source.load()
        if self.load().get('replan_id'):
            from cogito_replan_store import ReplanStore
            rp = ReplanStore(self.root,self.load()['replan_id']).load()
            candidates = {entry['worktree'] for field in ('transfer_plans','transfers')
                          for entry in rp.get(field,{}).values() if entry.get('worktree')}
            for sl in (rp.get('proposal') or {}).get('package',{}).get('slices',[]):
                path = (self.root/sl['worker']['worktree']).resolve()
                if path.exists(): candidates.add(str(path))
            for name in candidates:
                path = Path(name).resolve()
                if not path.is_relative_to(self.root): raise CogitoError('transfer worktree escapes project')
                index,tree = capture_index_and_worktree_trees(path)
                worktrees[str(path)] = dict(head=source._git_at(path,'rev-parse','HEAD'),
                    branch=source._git_at(path,'branch','--show-current'),index_tree=index,content_tree=tree)
        index, tree = capture_index_and_worktree_trees(self.root)
        graph_path = self.root/'docs/cogito/project-graph.json'
        paths, slices = set(), set()
        for run_id in dict.fromkeys([*self.load()['run_ids'], *extra_runs]):
            run = RunStore(self.root,run_id)
            if run.load().get('package_hash'):
                package = run.approved_package()
                paths.update(package.get('approved_paths', []))
                for item in package.get('slices',[]): slices.add(item['id'])
                for task in package.get('execution_dag',{}).get('tasks',[]):
                    paths.update(task.get('paths', []))
        state = self.load()
        saved = dict(runs=runs,tasks=current['tasks'],worktrees=worktrees,
            source_event_hash=current['last_event_hash'],package_hash=current.get('package_hash'),
            effective_contract_hash=current.get('effective_contract_hash'),
            delivery=dict(head=source._git('rev-parse','HEAD'),branch=source._git('branch','--show-current'),index_tree=index,content_tree=tree),
            graph=load_json(graph_path) if graph_path.exists() else None,
            scope=dict(paths=sorted(paths),slice_ids=sorted(slices),reason=state['reason']))
        saved['runtime'] = capture_runtime(
            self.root, self.disposition_id, runs, state.get('replan_id'))
        return saved

    def _validate_saved_work(self, saved):
        """Allow only our journal cancellation and Graph release during replay."""
        from cogito_execution_registry import quiescent
        current = self._capture(extra_runs=saved['runs'])
        a,b = saved['delivery'],current['delivery']
        runtime_paths = validate_runtime(
            self.root, self.disposition_id, saved, self.load(), transition=True,
            first_tree=a['content_tree'], second_tree=b['content_tree'])
        for run_id, old in saved['runs'].items():
            if not quiescent(self.root, run_id, allow_external_receipts=True):
                raise CogitoError('saved work has an active executor; stop before retry')
            new = current['runs'][run_id]
            events = read_events(RunStore(self.root, run_id).events_path)
            anchor = next((i for i,e in enumerate(events) if e['event_hash']==old['event_hash']), None)
            if anchor is None or any(e['type'] != 'cancel' or not str(e.get('action_id','')).startswith('disposition-') for e in events[anchor+1:]):
                raise CogitoError('source changed after saved stop intent')
            expected_tasks = copy.deepcopy(old['tasks'])
            if any(e['type'] == 'cancel' for e in events[anchor+1:]):
                for task in expected_tasks.values():
                    if task['status'] in {'leased', 'running'}:
                        task.update(status='blocked', released_by=self.disposition_id)
            if expected_tasks != new['tasks'] or old['package_hash'] != new['package_hash']:
                raise CogitoError('saved tasks changed after stop intent')
        if current['worktrees'].keys() != saved['worktrees'].keys():
            raise CogitoError('saved worktree set changed after stop intent')
        for path, old in saved['worktrees'].items():
            new = current['worktrees'][path]
            if path == str(self.root):
                if any(old[k] != new[k] for k in ('head','branch','index_tree')):
                    raise CogitoError('saved delivery worker changed after stop intent')
                require_same_product(self.root, old['content_tree'], new['content_tree'], runtime_paths)
            elif old != new:
                raise CogitoError('saved worker content changed after stop intent')
        if any(a[key] != b[key] for key in ('head','branch','index_tree')):
            raise CogitoError('delivery changed after stop intent')
        require_same_product(self.root, a['content_tree'], b['content_tree'], runtime_paths)

    def _require_same_product(self, first, second, allowed=()):
        require_same_product(self.root, first, second, allowed)

    def _validate_no_change(self, proposal):
        state = self.load(); source = self.source(); current = source.load()
        proof = proposal.get('no_change_evidence')
        if isinstance(proof, dict) and proof.get('no_work') is True:
            if set(proof) != {'no_work', 'head', 'content_tree', 'evidence_paths'} or proof['evidence_paths'] != []:
                raise CogitoError('no-work proof requires exact HEAD/tree and empty evidence_paths')
            if current['agent_results'] or current.get('amendments') or state.get('replan_id'):
                raise CogitoError('reported implementation or RP work requires normal disposition acceptance')
            saved = state['snapshot']
            if (proof['head'] != saved['delivery']['head']
                    or source._git('rev-parse', 'HEAD') != proof['head']):
                raise CogitoError('no-work proof does not match the saved original baseline')
            if current.get('package_hash') and source.approved_package()['baseline_commit'] != proof['head']:
                raise CogitoError('delivery contains new commits; use normal disposition acceptance')
            now = self._capture()
            runtime_paths = validate_runtime(
                self.root, self.disposition_id, saved, state,
                first_tree=saved['delivery']['content_tree'],
                second_tree=now['delivery']['content_tree'])
            try:
                require_same_product(
                    self.root, proof['content_tree'], saved['delivery']['content_tree'], runtime_paths)
            except CogitoError as exc:
                raise CogitoError('no-work proof does not match the saved original baseline') from exc
            baseline_tree = source._git('rev-parse', proof['head']+'^{tree}')
            for binding in [saved['delivery'], *saved['worktrees'].values(), now['delivery'], *now['worktrees'].values()]:
                for key in ('index_tree', 'content_tree'):
                    require_same_product(self.root, baseline_tree, binding[key], runtime_paths)
            return
        if state.get('source_state') not in {'awaiting-human','accepted'}:
            raise CogitoError('no-change retention requires a previously verified delivery awaiting acceptance')
        proof = proposal.get('no_change_evidence')
        if not isinstance(proof, dict) or set(proof) != {'head','content_tree','evidence_paths'}:
            raise CogitoError('no-change retention requires head, content_tree and evidence_paths')
        if not isinstance(proof['evidence_paths'], list) or not proof['evidence_paths']:
            raise CogitoError('no-change retention requires controlled evidence')
        if not all(isinstance(proof[k],str) and re.fullmatch(r'[0-9a-f]{40,64}',proof[k]) for k in ('head','content_tree')):
            raise CogitoError('retention head and content_tree must be Git object identifiers')
        if proof['head'] != state['snapshot']['delivery']['head']:
            raise CogitoError('retention evidence targets a different saved HEAD')
        saved = state['snapshot']
        now = self._capture()['delivery']
        runtime_paths = validate_runtime(
            self.root, self.disposition_id, saved, state,
            first_tree=saved['delivery']['content_tree'], second_tree=now['content_tree'])
        require_same_product(self.root, proof['content_tree'], saved['delivery']['content_tree'], runtime_paths)
        require_same_product(self.root, proof['content_tree'], now['content_tree'], runtime_paths)
        require_same_product(self.root, now['content_tree'], source._git('rev-parse',now['head']+'^{tree}'), runtime_paths)
        evidence = []
        evidence_root = (source.run_dir/'evidence').resolve()
        for name in proof['evidence_paths']:
            if not isinstance(name,str): raise CogitoError('evidence paths must be strings')
            path = Path(name).resolve()
            if not path.is_relative_to(evidence_root): raise CogitoError('retention evidence escapes source ledger')
            from cogito_evidence_contract import validate_check_evidence
            record = load_json(path); validate_check_evidence(record)
            evidence.append(record)
        heads = {item.get('head_commit') for item in evidence}
        if len(heads) != 1: raise CogitoError('retention evidence must describe one delivery')
        for item in evidence:
            require_same_product(self.root, item['worktree_binding']['content_tree'], proof['content_tree'], runtime_paths)
        source._validate_evidence(source.approved_package(), evidence, snapshot=source._events.snapshot(),
            phase='post-integration', current_head=next(iter(heads)), validate_supplied=True)

    @mutation
    def pause(self, reason, action_id):
        request = dict(reason=reason)
        if self._replay(action_id,'pause',request): return self.load()
        nonempty(reason,'reason'); state = self.load()
        intent = 'disposition-pause-intent:'+action_id
        if state['state'] == 'executing':
            self._emit('disposition-pause-started', dict(reason=reason, retired_followup_run_id=state['proposal'].get('followup_run_id')),
                intent,'pause-intent',request)
        elif state['state'] == 'pausing':
            matches = [e for e in read_events(self.events_path) if e['action_id']==intent]
            if not matches: raise CogitoError('retry pause with original action_id')
            require_same_request(matches[0],request_fingerprint('pause-intent',**request),intent)
        else: raise CogitoError('only an executing disposition may pause')
        followup_id = state['proposal'].get('followup_run_id')
        from cogito_execution_registry import request_stop, terminate_overdue, quiescent, snapshot
        if followup_id:
            run = RunStore(self.root,followup_id)
            if run.load()['state'] not in {'blocked','accepted','cancelled','superseded'}:
                run.transition('block',{'reason':reason},'disposition-pause-block:'+action_id)
            request_stop(self.root,followup_id,deadline_seconds=60)
            terminate_overdue(self.root,followup_id)
            active = {t['agent_id'] for t in run.load()['tasks'].values() if t['status'] in {'leased','running'}}
            if not active <= set(snapshot(self.root,followup_id)['entries']):
                raise CogitoError('register every active followup executor before completing pause')
            if not quiescent(self.root,followup_id,allow_external_receipts=True):
                raise CogitoError('followup executors are not confirmed stopped')
        saved_id = 'disposition-pause-saved:'+action_id
        saved_events = [e for e in read_events(self.events_path) if e['action_id']==saved_id]
        saved = saved_events[0]['payload']['snapshot'] if saved_events else self._capture(extra_runs=[followup_id] if followup_id else [])
        if not saved_events:
            self._emit('disposition-pause-saved',{'snapshot':saved},saved_id,'pause-saved',request)
        self._validate_saved_work(saved)
        from cogito_disposition_archive import pin_snapshot
        pin_snapshot(self.root,self.disposition_id,saved)
        graph_path = self.root/'docs/cogito/project-graph.json'
        if graph_path.exists():
            graph = load_json(graph_path); expected = copy.deepcopy(saved['graph'])
            if expected and expected.get('active_run_id') == followup_id: expected['active_run_id'] = None
            if graph not in (saved['graph'],expected): raise CogitoError('Graph changed during pause')
        if followup_id:
            run = RunStore(self.root,followup_id)
            if run.load()['state'] not in {'accepted','cancelled','superseded'}:
                run.transition('cancel',{'authorized':True,'reason':reason},'disposition-pause-cancel:'+action_id)
        if graph_path.exists() and graph != expected: atomic_write_json(graph_path,expected)
        scopes = [state.get('scope',{}),saved['scope'],state['proposal']['impact']]
        scope = dict(paths=sorted({p for x in scopes for p in x.get('paths',[])}),
            slice_ids=sorted({p for x in scopes for p in x.get('slice_ids',[])}),reason=reason,
            unknown=any(x.get('unknown',False) for x in scopes))
        return self._emit('disposition-paused',{'snapshot':saved,'scope':scope,'retired_followup_run_id':followup_id},action_id,'pause',request)

    @mutation
    def stop(self, action_id):
        if self._replay(action_id,'stop',{}):
            self._delegate_replan()
            return self.load()
        state = self.load()
        if state['state'] != 'stopping': raise CogitoError('stop requires stopping disposition')
        intent_id = 'disposition-stop-intent:'+action_id
        intents = [e for e in read_events(self.events_path) if e['type']=='disposition-stop-started']
        if intents:
            if intents[0]['action_id'] != intent_id: raise CogitoError('retry stop with original action_id')
            saved = intents[0]['payload']['snapshot']
        else:
            self._request_stop()
            from cogito_execution_registry import quiescent, snapshot, terminate_overdue
            for run_id in state['run_ids']:
                terminate_overdue(self.root, run_id)
                registry = snapshot(self.root,run_id)
                active = {t['agent_id'] for t in RunStore(self.root,run_id).load()['tasks'].values() if t['status'] in {'leased','running'}}
                if not active <= set(registry['entries']): raise CogitoError('active worker lacks executor registration')
                if not quiescent(self.root,run_id,allow_external_receipts=True):
                    raise CogitoError('executors not confirmed stopped; disposition remains stopping')
            saved = self._capture()
            if saved['graph'] != state.get('graph_before'): raise CogitoError('Project Graph changed while stopping')
            if saved != self._capture(): raise CogitoError('work changed while saving; stop all writers and retry')
            self._emit('disposition-stop-started', {'snapshot':saved},intent_id,'stop-intent',{})
        self._validate_saved_work(saved)
        from cogito_disposition_archive import pin_snapshot
        pin_snapshot(self.root, self.disposition_id, saved)
        before = saved['graph']; after = copy.deepcopy(before)
        if after:
            if after.get('active_run_id') in state['run_ids']: after['active_run_id'] = None
            if state.get('cancel_source'):
                for sid in saved['scope']['slice_ids']:
                    if sid in after.get('slices',{}): after['slices'][sid]['disposition'] = 'cancelled'
            actual = load_json(self.root/'docs/cogito/project-graph.json')
            if actual not in (before,after): raise CogitoError('Project Graph changed during stop completion')
        source = self.source()
        if state.get('cancel_source') and source.load()['state'] not in {'accepted','cancelled','superseded'}:
            source.transition('cancel', {'authorized':True,'reason':state['reason']},'disposition-cancel:'+self.disposition_id)
        if after is not None and actual != after:
            atomic_write_json(self.root/'docs/cogito/project-graph.json',after)
        self._emit('disposition-stopped',{'snapshot':saved,'scope':saved['scope']},action_id,'stop',{})
        self._delegate_replan()
        return self.load()

    def _delegate_replan(self):
        state = self.load()
        if state.get('replan_id'):
            from cogito_replan_store import ReplanStore
            ReplanStore(self.root,state['replan_id']).delegate_disposition(self.disposition_id,'dp-delegate:'+self.disposition_id)

    @mutation
    def release(self, action_id):
        if self._replay(action_id, 'release', {}):
            return self.load()
        state = self.load()
        if state['state'] not in {'analyzing', 'reviewing', 'awaiting-approval'}:
            raise CogitoError('release delivery before approving execution of a disposition')
        from cogito_disposition_archive import release_delivery
        saved = state.get('pause_snapshot') or state['snapshot']
        runtime_paths = validate_runtime(self.root, self.disposition_id, saved, state)
        receipt = release_delivery(
            self.root, self.disposition_id, saved, runtime_paths=runtime_paths)
        return self._emit('disposition-delivery-released', {'snapshot_hash':hash_json(saved), 'receipt':receipt},
                          action_id, 'release', {})

    @mutation
    def propose(self, proposal, action_id):
        request = dict(proposal=proposal)
        if self._replay(action_id,'propose',request): return self.load()
        validate_proposal(proposal)
        return self._emit('proposal-prepared',{'proposal':copy.deepcopy(proposal),'proposal_hash':hash_json(proposal)},action_id,'propose',request)

    @mutation
    def review(self, review, action_id):
        request = dict(review=review)
        if self._replay(action_id,'review',request): return self.load()
        state = self.load()
        if state['state'] != 'reviewing':
            raise CogitoError('review requires a current disposition proposal')
        validate_review(review,state['proposal'],state['proposal_hash'])
        if review.get('verdict','approved') != 'approved':
            reason = review.get('summary') or review.get('assessment')
            if isinstance(reason, dict):
                import json
                reason = json.dumps(reason, ensure_ascii=False)
            return self._emit('proposal-rejected',{'reason':reason,'review':review},action_id,'review',request)
        return self._emit('proposal-reviewed',{'review':review,'proposal_hash':state['proposal_hash']},action_id,'review',request)

    @mutation
    def approve(self, proposal_hash, authorized, action_id):
        request = dict(proposal_hash=proposal_hash,authorized=authorized)
        if self._replay(action_id,'approve',request): return self.load()
        state = self.load()
        if state['state'] != 'awaiting-approval':
            raise CogitoError('approval requires an independently reviewed disposition proposal')
        if authorized is not True: raise CogitoError('explicit human approval is required')
        if proposal_hash != state.get('proposal_hash'): raise CogitoError('approval targets stale proposal')
        proposal = state['proposal']; followup_id = proposal.get('followup_run_id')
        binding = None
        if followup_id:
            if followup_id in state['run_ids']: raise CogitoError('followup must be a separate run')
            followup = RunStore(self.root,followup_id).load()
            if followup['state'] != 'awaiting-package-approval': raise CogitoError('followup must have a prepared unapproved Package')
            binding = followup.get('candidate_package_hash')
            if not binding: raise CogitoError('followup Package is unavailable')
            if proposal.get('followup_package_hash') != binding: raise CogitoError('followup Package changed since proposal review')
            candidate = (followup.get('planning') or {}).get('candidate')
            if not candidate or not candidate.get('package'):
                raise CogitoError('followup candidate snapshot is unavailable')
            draft = candidate['package']; run = RunStore(self.root, followup_id)
            run._planning_approval_binding(followup)
            run._validate_policy(draft)
            if (run._git('rev-parse', 'HEAD') != draft['baseline_commit']
                    or run._git('branch', '--show-current') != draft['delivery_branch']):
                raise CogitoError('followup baseline changed; revise its Package before disposition approval')
            allowed = {'docs/cogito/project-graph.json', 'docs/cogito/packages/'+followup_id+'.json'}
            allowed.update(sl[role]['path'] for sl in draft['slices'] for role in ('spec','plan'))
            allowed.update(item['path'] for item in draft.get('source_registry', []) if item['disposition'] in {'adopted','updated'})
            for tree in capture_index_and_worktree_trees(self.root):
                dirty = set(filter(None, run._git('diff','--name-only','--no-ext-diff','--no-renames','-z',draft['baseline_commit'],tree,'--').split('\0')))
                if dirty - allowed:
                    raise CogitoError('followup requires a clean delivery checkout; preserve and release saved changes before approval')

        elif proposal['action'] == 'retain':
            self._validate_no_change(proposal)
        elif proposal['action'] != 'resume':
            raise CogitoError('disposition requires a prepared followup run for implementation and acceptance')
        if proposal['action'] == 'resume':
            source = self.source().load()
            if not state.get('replan_id') or source['state'] != 'blocked':
                raise CogitoError('only a paused replanning source may resume')
            self.source().validate_disposition_resume(self.disposition_id)
        return self._emit('disposition-approved',{**request,'followup_run_id':followup_id,'followup_package_hash':binding},action_id,'approve',request)

    @mutation
    def reject(self, reason, action_id):
        request = dict(reason=reason)
        if self._replay(action_id,'reject',request): return self.load()
        nonempty(reason,'reason')
        return self._emit('proposal-rejected',request,action_id,'reject',request)

    @mutation
    def complete(self, action_id, human_accepted=False):
        request = dict(human_accepted=human_accepted)
        if self._replay(action_id,'complete',request): return self.load()
        state = self.load()
        if state['state'] != 'executing': raise CogitoError('completion requires approved disposition')
        proposal = state['proposal']
        if proposal['action'] == 'resume':
            self.source().disposition_resume(self.disposition_id,'disposition-resume:'+self.disposition_id)
            resolution = dict(action='resume',source_run_id=state['source_run_id'])
        elif proposal['action'] == 'retain' and not proposal.get('followup_run_id'):
            if human_accepted is not True:
                raise CogitoError('retained content requires explicit human acceptance')
            self._validate_no_change(proposal)
            resolution = dict(action='retain', no_change_evidence=proposal['no_change_evidence'], human_accepted=True)
        else:
            followup = RunStore(self.root,proposal['followup_run_id']).load()
            if followup['state'] != 'accepted': raise CogitoError('followup must complete required acceptance before releasing holds')
            if followup['package_hash'] != state['approval']['followup_package_hash']:
                raise CogitoError('followup Package changed after disposition approval')
            resolution = dict(action=proposal['action'],followup_run_id=proposal['followup_run_id'],event_hash=followup['last_event_hash'])
        if proposal['action'] != 'resume':
            for run_id in state['run_ids']:
                run = RunStore(self.root, run_id)
                if run.load()['state'] not in {'accepted', 'cancelled', 'superseded'}:
                    run.transition('cancel', {'authorized':True,'reason':'disposition completed'}, 'disposition-completion-cancel:'+self.disposition_id)
        return self._emit('disposition-completed',{'resolution':resolution},action_id,'complete',request)
