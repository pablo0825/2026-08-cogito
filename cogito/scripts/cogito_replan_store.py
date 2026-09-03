"""Dedicated replanning Gate: frozen proposal, independent review and handoff journal."""
from __future__ import annotations
import copy
import re
from functools import wraps
from pathlib import Path
from typing import Any, Mapping
from cogito_actions import request_fingerprint, require_same_request
from cogito_common import CogitoError, atomic_create_json, atomic_write_json, hash_json, load_json
from cogito_contracts import package_hash, validate_package_with_limits
from cogito_events import append_event, read_events
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_project_graph import formalize_project_graph, validate_project_graph
from cogito_replan_lock import project_lock, replan_authority, replans
from cogito_replan_state import project_replan, TERMINAL
from cogito_replan_snapshot import ReplanRuntime, entries as snapshot_entries
from cogito_run_store import RunStore
from cogito_scheduler import tasks_with_dependencies


def mutation(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with project_lock(self.root), replan_authority(self.replan_id):
            try:
                return method(self, *args, **kwargs)
            except OSError as exc:
                raise CogitoError("replan storage operation failed; inspect history and retry the same action_id: " + str(exc)) from exc
    return call


def text_field(value, name):
    if not isinstance(value, str) or not value.strip():
        raise CogitoError(f'{name} must be nonempty text')
    return value


class ReplanStore:
    def __init__(self, root, replan_id):
        if not re.fullmatch(r'RP-[A-Za-z0-9._-]+', replan_id):
            raise CogitoError('replan_id must be a safe RP-* identifier')
        self.root = Path(root).resolve()
        self.replan_id = replan_id
        self.directory = self.root / '.cogito/replans' / replan_id
        self.events_path = self.directory / 'events.jsonl'

    def load(self):
        state = project_replan(read_events(self.events_path))
        if state.get('proposal') and state['state'] in {'reviewing','awaiting-approval','awaiting-decision'}:
            successor = RunStore(self.root, state['successor_run_id']).load()
            state['proposal_stale'] = successor.get('candidate_package_hash') != package_hash(state['proposal']['package'])
            if state['proposal_stale']:
                state['next_action'] = 'finish current successor planning, replace the RP proposal and repeat independent review'
        atomic_write_json(self.directory / 'state.json', state)
        return state

    def _replay(self, action_id, operation, request):
        text_field(action_id, 'action_id')
        digest = request_fingerprint(operation, **request)
        matches = [e for e in read_events(self.events_path) if e.get('action_id') == action_id]
        if matches:
            require_same_request(matches[0], digest, action_id)
            return self.load()
        return None

    def _emit(self, kind, payload, action_id, operation, request):
        old = read_events(self.events_path)
        if old:
            payload = {**payload, 'runtime_logs': self._runtime(project_replan(old)).log_bindings()}
        event = dict(type=kind, payload=payload, action_id=action_id,
                     request_hash=request_fingerprint(operation, **request))
        project_replan([*old, event])
        append_event(self.events_path, event, old[-1]['event_hash'] if old else '0'*64)
        return self.load()

    def source(self):
        return RunStore(self.root, self.load()['source_run_id'])

    def successor(self):
        return RunStore(self.root, self.load()['successor_run_id'])

    @mutation
    def begin(self, source_run_id, successor_run_id, reason, action_id):
        request = dict(source_run_id=source_run_id, successor_run_id=successor_run_id, reason=reason)
        replay = self._replay(action_id, 'begin', request)
        if not replay:
            if self.events_path.exists():
                raise CogitoError('replan already exists')
            for other in replans(self.root):
                if other['state'] not in TERMINAL:
                    raise CogitoError('another replan already owns the project')
            source, successor = RunStore(self.root, source_run_id), RunStore(self.root, successor_run_id)
            current = source.load()
            if current['state'] in {'cancelled', 'superseded'} or source_run_id == successor_run_id:
                raise CogitoError('replan needs an approved active or accepted source and a new successor')
            package = source.approved_package()
            from cogito_execution_registry import snapshot
            active = {task['agent_id'] for task in current['tasks'].values() if task['status'] in {'leased','running'}}
            if not active <= set(snapshot(self.root,source_run_id)['entries']):
                raise CogitoError('register actual active executors before beginning replan; stop dispatch while resolving handles')
            if successor.events_path.exists():
                raise CogitoError('successor run must be new')
            graph = load_json(self.root / 'docs/cogito/project-graph.json')
            validate_project_graph(graph)
            if graph.get('active_run_id') not in {None, source_run_id}:
                raise CogitoError('another run owns Project Graph')
            text_field(reason,'reason')
            self._emit('replan-created', dict(
                **request, replan_id=self.replan_id,
                source_package_hash=package_hash(package), source_event_hash=current['last_event_hash'],
                source_state=current['state'], graph_before=graph,
            ), action_id, 'begin', request)
        # The fence is durable BEFORE stopping. Replaying completes interrupted begin effects.
        if self.load()["state"] == "stopping": self._stop_request()
        return self.load()

    def _stop_request(self):
        from cogito_execution_registry import request_stop
        source = self.source()
        if source.load()['state'] != 'accepted':
            source.transition('block', {'reason': 'replanning '+self.replan_id}, 'replan-block:'+self.replan_id)
        request_stop(self.root, source.run_id, deadline_seconds=60)

    def _capture(self):
        source = self.source()
        current = source.load()
        for evidence_path, ledger in current.get('evidence', {}).items():
            if hash_json(load_json(Path(evidence_path))) != ledger.get('evidence_hash'):
                raise CogitoError('source runtime evidence differs from its recorded hash')
        worktrees = {}
        for task in current['tasks'].values():
            if task.get('worktree'):
                path = Path(task['worktree']).resolve()
                path.relative_to(self.root)
                index, tree = capture_index_and_worktree_trees(path)
                worktrees[str(path)] = dict(index_tree=index, content_tree=tree,
                    head=source._git_at(path,'rev-parse','HEAD'), branch=source._git_at(path,'branch','--show-current'))
        index, tree = capture_index_and_worktree_trees(self.root)
        saved = dict(source_event_hash=current['last_event_hash'], package_hash=current['package_hash'],
            effective_contract_hash=current['effective_contract_hash'], tasks=current['tasks'],
            worktrees=worktrees, delivery=dict(index_tree=index, content_tree=tree,
                head=source._git('rev-parse','HEAD'),branch=source._git('branch','--show-current')),
            graph=load_json(self.root/'docs/cogito/project-graph.json'))
        saved['runtime'] = self._runtime().capture(saved['delivery'], worktrees)
        return saved

    def _runtime(self, state=None):
        state = state or self.load()
        source = RunStore(self.root, state['source_run_id'])
        package = source.approved_package()
        documents = [d for sl in package['slices'] for d in (sl['spec'], sl['plan'])]
        documents.extend(package.get('source_registry', []))
        if package.get('shared_understanding', {}).get('path'):
            documents.append(package['shared_understanding'])
        for document in documents:
            source._validate_content_hash(document['path'], document['hash'])
        protected = {d['path'] for d in documents}
        return ReplanRuntime(self.root, state, protected)

    def _verified_successor_links(self, state):
        """Only journaled, exactly verified worktree gitlinks may leave delivery."""
        links: dict[str, str] = {}
        if state['state'] != 'handing-off':
            return links
        package = state['proposal']['package']
        approved = {str((self.root / sl['worker']['worktree']).resolve()): sl['worker']['branch']
                    for sl in package['slices']}
        base = package['baseline_commit']
        base_tree = self.source()._git('rev-parse', base + '^{tree}')
        baseline = dict(head=base, index_tree=base_tree, content_tree=base_tree)
        for path, branch in approved.items():
            worktree = Path(path)
            for source_path in state['snapshot']['worktrees']:
                original = Path(source_path)
                if original != self.root and (worktree == original or original in worktree.parents
                                              or worktree in original.parents):
                    raise CogitoError('successor worktree overlaps preserved source worktree')
            if not worktree.exists():
                continue
            bindings = [self._last_targets(state).get(path, baseline)]
            plans = [p for p in state['transfer_plans'].values() if p['worktree'] == path]
            if plans and plans[-1]['task_id'] not in state['transfers']:
                # _transfer reconciles precisely these journaled crash points.
                plan = plans[-1]
                bindings = [plan['before'], plan['after'], dict(
                    head=plan['before']['head'], index_tree=plan['after']['index_tree'],
                    content_tree=plan['after']['content_tree'])]
            actual = self._target_binding(worktree)
            if (actual not in bindings
                    or self.source()._git_at(worktree, 'branch', '--show-current') != branch):
                raise CogitoError('transferred worktree changed before activation')
            relative = worktree.relative_to(self.root).as_posix()
            # A preexisting product entry cannot be hidden by a new target.
            for field in ('index_tree', 'content_tree'):
                if any(p == relative or p.startswith(relative + '/') for p in
                       snapshot_entries(self.root, state['snapshot']['delivery'][field])):
                    raise CogitoError('successor worktree overlaps stopped delivery content')
            links[relative] = actual['head']
        return links

    @mutation
    def stop(self, action_id):
        if self._replay(action_id,'stop',{}): return self.load()
        state = self.load()
        if state['state'] != 'stopping': raise CogitoError('stop capture requires stopping stage')
        self._stop_request()
        from cogito_execution_registry import snapshot, quiescent, terminate_overdue
        terminate_overdue(self.root,state['source_run_id'])
        registry = snapshot(self.root,state['source_run_id'])
        active = {t['agent_id'] for t in self.source().load()['tasks'].values() if t['status'] in {'leased','running'}}
        if not active <= set(registry['entries']):
            raise CogitoError('active Worker has no registered executor; obtain its actual control handle')
        if not quiescent(self.root,state['source_run_id'],allow_external_receipts=True):
            raise CogitoError('executors are not confirmed stopped; replan remains stopping')
        saved = self._capture()
        if saved['graph'] != state['graph_before']:
            raise CogitoError('Project Graph changed during stopping')
        if saved != self._capture():
            raise CogitoError('source changed while preserving work; retry after all writers stop')
        return self._emit('replan-stopped',{'snapshot':saved},action_id,'stop',{})

    def _assert_source(self, proposal=None, activated=False):
        state = self.load()
        successor = RunStore(self.root, state['successor_run_id'])
        if successor.events_path.exists():
            successor.load()
        saved = state['snapshot']
        actual = self._capture()
        events = self.source()._events.read()
        closed_by_us = (events[-1]['type']=='run-superseded' and events[-1]['payload'].get('replan_id')==self.replan_id and events[-1]['previous_event_hash']==saved['source_event_hash'])
        if (actual['source_event_hash'] != saved['source_event_hash'] and not closed_by_us) or actual['package_hash'] != saved['package_hash'] or actual['effective_contract_hash'] != saved['effective_contract_hash']:
            raise CogitoError('source run changed since stop checkpoint')
        # Feature worker trees remain immutable; mini runs use the delivery checkout.
        for path, binding in saved['worktrees'].items():
            if Path(path) != self.root and actual['worktrees'].get(path) != binding:
                raise CogitoError('saved source worktree drifted')
        if any(actual['delivery'][k] != saved['delivery'][k] for k in ('head','branch')):
            raise CogitoError('delivery baseline drifted since stop checkpoint')
        runtime = self._runtime(state)
        frozen_runtime = runtime.assert_snapshot(saved)
        for event in read_events(self.events_path):
            if 'runtime_logs' in event['payload']:
                runtime.assert_logs(event['payload']['runtime_logs'])
        successor_links = self._verified_successor_links(state)
        source_links = runtime.worker_links(saved['worktrees'])
        runtime.assert_index(saved['delivery']['index_tree'], actual['delivery']['index_tree'],
                             frozen_runtime, source_links)
        allowed = {'docs/cogito/project-graph.json'}
        if proposal:
            package = proposal['package']
            allowed.add(f"docs/cogito/packages/{package['run_id']}.json")
            olddocs = {d['path'] for s in self.source().approved_package()['slices'] for d in (s['spec'],s['plan'])}
            allowed.update(d['path'] for s in package['slices'] for d in (s['spec'],s['plan']) if d['path'] not in olddocs)
        for field in ('index_tree','content_tree'):
            runtime.assert_frozen_tree(actual['delivery'][field], frozen_runtime)
            before = runtime.product_tree(saved['delivery'][field], immutable_files=frozen_runtime,
                                          worker_links=source_links)
            after = runtime.product_tree(actual['delivery'][field], worker_links=source_links | successor_links,
                                         immutable_files=frozen_runtime)
            changed = set(filter(None, self.source()._git('diff','--name-only','--no-renames','-z',before,after,'--').split('\0')))
            if changed - allowed:
                raise CogitoError('delivery content drifted outside new control documents: '
                                  + ', '.join(sorted(changed - allowed)))
        expected = state['approval']['graph'] if activated else saved['graph']
        if actual['graph'] != expected: raise CogitoError('Project Graph drifted; preserve state and reconcile')

    @mutation
    def propose(self, proposal, action_id):
        request = {'proposal':proposal}
        if self._replay(action_id,'propose',request): return self.load()
        state = self.load()
        if state['state'] not in {'analyzing','reviewing','awaiting-approval','awaiting-decision'}:
            raise CogitoError('proposal revision is not legal now')
        if not isinstance(proposal,dict): raise CogitoError('proposal must be an object')
        proposal = copy.deepcopy(proposal)
        text_field(proposal.get('author_id'),'author_id')
        differences = proposal.get('differences')
        if not isinstance(differences,dict): raise CogitoError('differences must be an object')
        for field in ('requirements','api','boundary','acceptance','cost','revalidation'):
            text_field(differences.get(field),'differences.'+field)
        package = proposal.get('package')
        if not isinstance(package,dict): raise CogitoError('proposal requires successor Package')
        new = self.successor()
        validate_package_with_limits(package,new.workflow['limits'])
        if package['run_id'] != new.run_id: raise CogitoError('proposal targets wrong successor')
        current = new.load()
        if current['state'] != 'awaiting-package-approval' or current['candidate_package_hash'] != package_hash(package):
            raise CogitoError('successor Package must pass normal preparation Gates before proposal')
        new._planning_approval_binding(current)
        self._assert_source(proposal)
        if package['baseline_commit'] != state['snapshot']['delivery']['head']:
            raise CogitoError('successor baseline must match saved delivery HEAD')
        oldids = set(state['snapshot']['graph']['slices'])
        for sl in package['slices']:
            if sl['id'] in oldids: raise CogitoError('successor must use new Slice IDs')
            if not set(sl.get('lineage',[])) <= oldids: raise CogitoError('unknown Slice lineage')
        manifest = proposal.get('work')
        if not isinstance(manifest,list) or not all(isinstance(row,dict) for row in manifest): raise CogitoError('proposal needs complete work manifest')
        source_tasks = state['snapshot']['tasks']
        targets = {t['id']:t for t in package['execution_dag']['tasks']}
        if {row.get('source_task_id') for row in manifest} != set(source_tasks) or len(manifest) != len(source_tasks):
            raise CogitoError('manifest must classify every source task exactly once')
        used = set()
        for row in manifest:
            if row.get('disposition') not in {'retain','adapt','omit'}: raise CogitoError('invalid work disposition')
            text_field(row.get('reason'),'work reason')
            if row.get('validation') not in {'reuse','rerun'}: raise CogitoError('work validation must be reuse or rerun')
            if row['disposition'] == 'omit':
                if row.get('target_task_id') is not None or row['validation']=='reuse': raise CogitoError('omitted work cannot have a target or reused evidence')
                continue
            target = row.get('target_task_id')
            if target not in targets or target in used: raise CogitoError('manifest target must be unique and exist')
            used.add(target)
            oldtask = source_tasks[row['source_task_id']]
            targettask = targets[target]
            if not set(oldtask['paths']) <= set(targettask['paths']):
                raise CogitoError('carried work paths must belong to successor task')
            oldslice = oldtask.get('slice_id')
            newsl = next((s for s in package['slices'] if s['id']==targettask.get('slice_id')),None)
            if oldslice and (not newsl or oldslice not in newsl.get('lineage',[])):
                raise CogitoError('carried task requires explicit Slice lineage')
            if row['validation']=='reuse':
                if row['disposition']!='retain': raise CogitoError('adapted work must be revalidated')
                self._adoption(proposal,row,source_tree_only=True)
        reuse_targets = {row['target_task_id'] for row in manifest if row['validation']=='reuse'}
        reuse_slices = {targets[t].get('slice_id') for t in reuse_targets}
        if any(t.get('slice_id') in reuse_slices and t['id'] not in reuse_targets for t in targets.values()):
            raise CogitoError('a reused worktree cannot also contain changed or new tasks; split Slice or rerun')
        # Prove deterministic imports before review/approval, while a proposal
        # can still be revised. Never discover an intrinsic merge conflict only
        # after the user has approved and Graph activation has begun.
        simulated: dict[str | None, str] = {}
        transfer_trees = {}
        for row in manifest:
            if row['disposition']=='omit': continue
            target=targets[row['target_task_id']]
            slice_id=target.get('slice_id')
            before=simulated.get(slice_id, self.source()._git('rev-parse', package['baseline_commit']+'^{tree}'))
            source_task=source_tasks[row['source_task_id']]
            saved=state['snapshot']['worktrees'].get(source_task.get('worktree'))
            source_tree=saved['content_tree'] if saved else state['snapshot']['delivery']['content_tree']
            after=self._merge_tree(before, source_task.get('base_commit',package['baseline_commit']), source_tree, source_task['paths'])
            simulated[slice_id]=after
            transfer_trees[row['source_task_id']]=after
            if row['validation']=='reuse': self._adoption(proposal,row,target_tree=after)
        proposal['transfer_trees']=transfer_trees
        proposal['source_snapshot_hash'] = hash_json(state['snapshot'])
        digest = hash_json(proposal)
        return self._emit('proposal-prepared',{'proposal':proposal,'proposal_hash':digest},action_id,'propose',request)

    @mutation
    def review(self, review, action_id):
        request={'review':review}
        if self._replay(action_id,'review',request): return self.load()
        state=self.load()
        if not isinstance(review,dict) or not isinstance(review.get('assessment'),dict):
            raise CogitoError('review must include a structured assessment')
        if state['state']!='reviewing' or review.get('proposal_hash')!=state['proposal_hash']:
            raise CogitoError('independent review must reference current proposal')
        if state.get('proposal_stale'):
            raise CogitoError('successor planning changed; prepare a new RP proposal before review')
        reviewer=text_field(review.get('reviewer_id'),'reviewer_id')
        if reviewer==state['proposal']['author_id']: raise CogitoError('proposal author cannot independently review it')
        if review.get('findings')!=[]: raise CogitoError('resolve review findings before requesting approval')
        for key in ('impact','reuse','revalidation','handoff'):
            text_field(review.get('assessment',{}).get(key),'review assessment.'+key)
        self._assert_source(state['proposal'])
        return self._emit('proposal-reviewed',dict(review),action_id,'review',request)

    @mutation
    def reject(self, proposal_hash, reason, action_id):
        request=dict(proposal_hash=proposal_hash,reason=reason)
        if self._replay(action_id,'reject',request): return self.load()
        state=self.load()
        if proposal_hash!=state.get('proposal_hash'): raise CogitoError('rejection refers to stale proposal')
        text_field(reason,'reason')
        return self._emit('proposal-rejected',request,action_id,'reject',request)

    def _planned_graph(self, proposal):
        state=self.load()
        graph=copy.deepcopy(state['snapshot']['graph'])
        graph['active_run_id']=None
        if state['source_state']!='accepted':
            for sl in self.source().approved_package()['slices']:
                graph['slices'][sl['id']]['disposition']='superseded'
        return formalize_project_graph(graph,proposal['package'],state['successor_run_id'])

    @mutation
    def approve(self, proposal_hash, action_id):
        request={'proposal_hash':proposal_hash}
        replay=self._replay(action_id,'approve',request)
        if not replay:
            state=self.load()
            if state['state']!='awaiting-approval' or proposal_hash!=state['proposal_hash']:
                raise CogitoError('human approval must reference independently reviewed current proposal')
            proposal=state['proposal']
            from cogito_disposition_scope import check_package
            check_package(self.root, proposal['package'], state['successor_run_id'])
            self._assert_source(proposal)
            new=self.successor()
            if new.load()['candidate_package_hash']!=package_hash(proposal['package']):
                raise CogitoError('prepared successor changed after review')
            new._validate_policy(proposal['package'])
            new._planning_approval_binding(new.load())
            # Durable authorization precedes publication, so recovery never invents approval.
            self._emit('successor-approved',{'proposal_hash':proposal_hash,'graph':self._planned_graph(proposal)},action_id,'approve',request)
        self._publish_successor()
        return self.load()

    def _publish_successor(self):
        state=self.load(); new=self.successor(); package=copy.deepcopy(state['proposal']['package'])
        digest=package_hash(package); package['package_hash']=digest
        current=new.load()
        if current.get('package_hash') is None and current.get('candidate_package_hash') != digest:
            raise CogitoError('successor candidate changed after authorization')
        planning_approval = new._planning_approval_binding(current) if current.get('package_hash') is None else (
            {'round': current['planning']['round'], 'proposal_hash': current['planning']['proposal_hash']}
            if current.get('planning', {}).get('revision') else None)
        relative=f'docs/cogito/packages/{new.run_id}.json'; path=self.root/relative
        if not atomic_create_json(path,package) and load_json(path)!=package:
            raise CogitoError('successor immutable Package differs from approved proposal')
        graph=state['approval']['graph']
        payload=dict(approved=True,package_path=relative,package_hash=digest,
            tasks=tasks_with_dependencies(package['execution_dag']),max_workers=package['policy_snapshot']['max_workers'],
            project_graph_hash=hash_json(graph),project_graph_snapshot=graph,limits=package['limits'])
        if planning_approval: payload['planning_approval']=planning_approval
        new.record('package-approved',payload,'replan-approval:'+self.replan_id,new._GATE_AUTHORITY)
        path.chmod(0o444)

    def _adoption(self, proposal, row, source_tree_only=False, target_tree=None):
        from cogito_replan_adoption import validate_adoption
        state=self.load(); source=self.source(); st=source.load(); task=st['tasks'][row['source_task_id']]
        binding=state['snapshot']['worktrees'].get(task.get('worktree'))
        if not binding: raise CogitoError('source has no verifiable saved worktree; rerun')
        records={p:load_json(Path(p)) for p in st['evidence']}
        return validate_adoption(source.approved_package(),proposal['package'],st,source._events.read(),
            row['source_task_id'],row['target_task_id'],records,binding['content_tree'],
            binding['content_tree'] if source_tree_only else target_tree)

    @mutation
    def handoff(self, action_id):
        request: dict[str, Any] = {}
        if self._replay(action_id,'handoff',request): return self.load()
        state=self.load()
        if state['state'] not in {'ready-for-handoff','handing-off'}:
            raise CogitoError('handoff requires approved proposal')
        self._publish_successor()
        state=self.load(); proposal=state['proposal']; graphpath=self.root/'docs/cogito/project-graph.json'
        targetgraph=state['approval']['graph']
        currentgraph=load_json(graphpath)
        if state['state']=='ready-for-handoff':
            self._assert_source(proposal)
            self._emit('handoff-started',{'proposal_hash':state['proposal_hash']},
                'handoff-intent:'+self.replan_id,'handoff-intent',{})
        self._assert_source(proposal,activated=currentgraph==targetgraph)
        if currentgraph!=targetgraph:
            atomic_write_json(graphpath,targetgraph)
        new=self.successor()
        if new.load()['state']=='start-gate':
            new.start_gate('replan-start:'+self.replan_id)
        if new.load()['state']!='executing': raise CogitoError('successor drifted during handoff')
        for row in proposal['work']:
            if row['source_task_id'] in self.load()['transfers']: continue
            self._transfer(row)
        # Validate every transferred tree again before enabling any dispatch.
        state=self.load()
        for path, expected in self._last_targets(state).items():
            actual=self._target_binding(Path(path))
            if actual!=expected: raise CogitoError('transferred worktree changed before activation')
        self._assert_source(proposal,activated=True)
        source=self.source()
        source_state = source.load()
        if source_state.get('human') or source_state.get('human_review_mandate') or state['source_state'] == 'awaiting-human':
            mandate = {'replan_id': self.replan_id, 'source_run_id': source.run_id,
                       'source_feedback_hash': source_state.get('human', {}).get('feedback_hash')}
            new.record('human-review-mandated', mandate,
                       'replan-human-mandate:' + self.replan_id, new._GATE_AUTHORITY,
                       request_hash=hash_json(mandate))
        if source.load()['state'] not in {'accepted','superseded'}:
            source.record('run-superseded',{'replan_id':self.replan_id,'successor_run_id':new.run_id},
                'replan-close:'+self.replan_id,source._GATE_AUTHORITY)
        for receipt in state['transfers'].values():
            if receipt.get('worktree'):
                new.record('work-carried', receipt, 'replan-carry:'+self.replan_id+':'+receipt['task_id'],new._GATE_AUTHORITY)
            if receipt.get('adoption'):
                new.record('work-adopted',{'receipt':receipt['adoption'],'worktree':receipt['worktree']},
                    'replan-adopt:'+self.replan_id+':'+receipt['task_id'],new._GATE_AUTHORITY)
        return self._emit('handoff-completed',{'successor_run_id':new.run_id},action_id,'handoff',request)

    def _target_binding(self, path):
        index,tree=capture_index_and_worktree_trees(path)
        source=self.source()
        return dict(head=source._git_at(path,'rev-parse','HEAD'),index_tree=index,content_tree=tree)

    def _last_targets(self,state):
        result={}
        for row in state['transfers'].values():
            if row.get('worktree'): result[row['worktree']]=row['binding']
        return result

    def _merge_tree(self, before, source_base, source_tree, paths):
        import os, subprocess, tempfile
        def git_call(*args, env=None, content=None):
            result=subprocess.run(['git','-C',str(self.root),*args],env=env,input=content,capture_output=True)
            if result.returncode:
                raise CogitoError('carryover cannot apply cleanly; revise the proposal before approval')
            return result.stdout
        patch=git_call('diff','--binary','--full-index',source_base,source_tree,'--',*paths)
        with tempfile.TemporaryDirectory(prefix='cogito-transfer-') as directory:
            env={**os.environ,'GIT_INDEX_FILE':str(Path(directory)/'index')}
            git_call('read-tree',before,env=env)
            if patch: git_call('apply','--cached','--3way',env=env,content=patch)
            return git_call('write-tree',env=env).decode().strip()

    def _transfer(self,row):
        state=self.load(); source=self.source(); new=self.successor(); package=state['proposal']['package']
        task_id=row['source_task_id']; savedtask=state['snapshot']['tasks'][task_id]
        if row['disposition']=='omit':
            self._emit('work-transferred',{'task_id':task_id,'disposition':'omit'},
                'transfer:'+task_id,'transfer',{'row':row})
            return
        task=next(t for t in package['execution_dag']['tasks'] if t['id']==row['target_task_id'])
        sl=next((s for s in package['slices'] if s['id']==task.get('slice_id')),None)
        if not sl: raise CogitoError('successor carried work requires a dedicated Slice worktree')
        path=(self.root/sl['worker']['worktree']).resolve()
        if not path.is_relative_to(self.root): raise CogitoError('successor worktree escapes repository')
        branch=sl['worker']['branch']; base=package['baseline_commit']
        if not path.exists():
            # git worktree add is itself recoverable: accept only our expected branch/base.
            branches=source._git('branch','--list',branch)
            if not branches: source._git('branch',branch,base)
            if source._git('rev-parse',branch)!=base: raise CogitoError('successor branch already contains unknown work')
            source._git('worktree','add',str(path),branch)
        if source._git_at(path,'branch','--show-current')!=branch: raise CogitoError('successor branch binding changed')
        plan=state.get('transfer_plans',{}).get(task_id)
        if plan is None:
            before=self._target_binding(path)
            expected=self._last_targets(state).get(str(path),dict(head=base,index_tree=source._git('rev-parse',base+'^{tree}'),content_tree=source._git('rev-parse',base+'^{tree}')))
            if before!=expected: raise CogitoError('successor worktree has unrecorded changes')
            saved=state['snapshot']['worktrees'].get(savedtask.get('worktree'))
            tree=saved['content_tree'] if saved else state['snapshot']['delivery']['content_tree']
            sourcebase=savedtask.get('base_commit',base)
            aftertree=self._merge_tree(before['content_tree'],sourcebase,tree,savedtask['paths'])
            if aftertree!=state['proposal']['transfer_trees'][task_id]:
                raise CogitoError('transfer content differs from reviewed proposal')
            if aftertree==before['content_tree']:
                aftercommit=before['head']
            else:
                aftercommit=source._git('commit-tree',aftertree,'-p',before['head'],'-m',f'Carry approved work from {source.run_id}/{task_id}\n\nCogito-Replan: {self.replan_id}')
            plan=dict(task_id=task_id,worktree=str(path),branch=branch,before=before,
                after=dict(head=aftercommit,index_tree=aftertree,content_tree=aftertree))
            self._emit('work-transfer-planned',plan,'transfer-plan:'+task_id,'transfer-plan',{'row':row})
        actual=self._target_binding(path)
        before,after=plan['before'],plan['after']
        if actual==before:
            source._git_at(path,'read-tree','--reset','-u',after['content_tree'])
            source._git_at(path,'update-ref','HEAD',after['head'],before['head'])
        elif actual==dict(head=before['head'],index_tree=after['index_tree'],content_tree=after['content_tree']):
            source._git_at(path,'update-ref','HEAD',after['head'],before['head'])
        elif actual!=after:
            raise CogitoError('transfer outcome is uncertain; preserve work and reconcile')
        receipt=dict(task_id=task_id,target_task_id=row['target_task_id'],disposition=row['disposition'],
            worktree=str(path),binding=after)
        if row['validation']=='reuse':
            receipt['adoption']=self._adoption(state['proposal'],row,target_tree=after['content_tree'])
            receipt['adoption']['target_implementation_head']=after['head']
        self._emit('work-transferred',receipt,'transfer:'+task_id,'transfer',{'row':row})

    @mutation
    def delegate_disposition(self, disposition_id, action_id):
        """Retire an RP only after its linked disposition has stopped all work.

        This also provides an append-only exit for legacy resolving-decision
        journals and partially applied handoffs. Transfer receipts stay intact.
        """
        request = dict(disposition_id=disposition_id)
        if self._replay(action_id, 'delegate-disposition', request): return self.load()
        state = self.load()
        if state['state'] in TERMINAL:
            raise CogitoError('terminal replan cannot delegate another disposition')
        from cogito_disposition_store import DispositionStore
        from cogito_execution_registry import quiescent
        disposition = DispositionStore(self.root, disposition_id).load()
        saved = disposition.get('snapshot', {})
        if (disposition.get('replan_id') != self.replan_id or
                disposition.get('source_run_id') != state['source_run_id']):
            raise CogitoError('disposition does not own this replan source')
        if disposition['state'] == 'stopping' or not saved:
            raise CogitoError('confirm disposition stop and snapshots before delegating replan')
        required = {state['source_run_id']}
        if self.successor().events_path.exists(): required.add(state['successor_run_id'])
        if not required <= set(saved.get('runs', {})):
            raise CogitoError('disposition must preserve source and successor snapshots')
        if not all(quiescent(self.root, run_id, allow_external_receipts=True) for run_id in required):
            raise CogitoError('source and successor executors must remain stopped')
        graph = load_json(self.root/'docs/cogito/project-graph.json')
        if graph.get('active_run_id') in required:
            raise CogitoError('disposition must release source and successor execution ownership')
        return self._emit('replan-disposition-started', request, action_id,
                          'delegate-disposition', request)

    @mutation
    def abandon(self, disposition, reason, action_id):
        request=dict(disposition=disposition,reason=reason)
        if disposition == 'cancel-source':
            # Cancellation owns an independent, recoverable disposition. Do
            # not record the old RP intent, which cannot track artifact review.
            state = self.load()
            if state['state'] in {'completed', 'abandoned'}:
                raise CogitoError('terminal replan cannot cancel its source')
            if not state.get('snapshot'):
                raise CogitoError('confirm all executors stopped and capture work before cancellation')
            if state['source_state'] == 'accepted':
                raise CogitoError('accepted source cannot cancel')
            from cogito_disposition_store import DispositionStore
            linked = state.get('disposition_id', 'DP-'+self.replan_id)
            store = DispositionStore(self.root, linked)
            store.begin(state['source_run_id'], reason, 'replan-cancel:'+action_id,
                        replan_id=self.replan_id, cancel_source=True)
            return store.stop('replan-cancel-stop:'+action_id)
        if self._replay(action_id,'abandon',request): return self.load()
        state=self.load()
        if state['state']!='resolving-decision':
            if disposition not in {'keep-paused','resume-source','cancel-source'}:
                raise CogitoError('explicit source disposition is required')
            text_field(reason,'reason')
            if disposition in {'resume-source','cancel-source'} and not state.get('snapshot'):
                raise CogitoError('confirm all executors stopped and capture work before resumption')
            if disposition in {'resume-source','cancel-source'} and state['source_state']=='accepted':
                raise CogitoError('accepted source cannot resume or cancel')
            if state.get('snapshot'): self._assert_source(state.get('proposal'))
            # A decision becomes durable only after its source operation is
            # feasible. In particular, abandoning a proposal does not withdraw
            # the human feedback which caused its escalation.
            if disposition == 'resume-source':
                self.source().validate_resume()
            graph=load_json(self.root/'docs/cogito/project-graph.json')
            if graph.get('active_run_id') not in {None,state['source_run_id']}:
                raise CogitoError('another run owns Project Graph')
            self._emit('replan-abandon-started',{**request,'action_id':action_id,'graph_before':graph},
                'abandon-intent:'+action_id,'abandon-intent',request)
            state=self.load()
        if any(state['decision'][key]!=value for key,value in {**request,'action_id':action_id}.items()):
            raise CogitoError('retry the recorded source disposition with the same action_id')
        source=self.source()
        if disposition=='resume-source':
            from cogito_execution_registry import begin_generation
            begin_generation(self.root,source.run_id,self.replan_id)
            source.resume_gate('replan-resume:'+self.replan_id)
            # Released executors cannot keep active leases. Preserve their work
            # as exact initial bindings for the replacement Worker.
            if source.load()['state']=='executing':
                for task_id,task in state['snapshot']['tasks'].items():
                    if task['status'] not in {'leased','running'}: continue
                    current=source.load()['tasks'][task_id]
                    if current['status'] in {'leased','running'}:
                        source.update_task(task_id,'blocked',task['agent_id'],'release:'+self.replan_id+':'+task_id)
                    if source.load()['tasks'][task_id]['status']=='blocked':
                        source.update_task(task_id,'pending',task['agent_id'],'requeue:'+self.replan_id+':'+task_id)
                    saved=state['snapshot']['worktrees'][task['worktree']]
                    source.record('work-carried',{'worktree':task['worktree'],'binding':{k:saved[k] for k in ('head','index_tree','content_tree')}},
                        'resume-binding:'+self.replan_id+':'+task_id,source._GATE_AUTHORITY)
        return self._emit('replan-abandoned',request,action_id,'abandon',request)
