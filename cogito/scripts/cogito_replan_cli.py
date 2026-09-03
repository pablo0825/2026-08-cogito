"""Public CLI for the independent replanning Gate and executor receipts."""
from __future__ import annotations
import argparse
from pathlib import Path
from cogito_common import CogitoError, load_json
from cogito_replan_lock import project_lock, check_run_fence
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore


def run(root, argv):
    parser=argparse.ArgumentParser(prog='cogito_gate.py replan')
    sub=parser.add_subparsers(dest='operation',required=True)
    for name in ('status','begin','stop','propose','review','approve','reject','handoff','abandon'):
        p=sub.add_parser(name);p.add_argument('--replan-id',required=True)
        if name!='status':p.add_argument('--action-id',required=True)
        if name=='begin':
            p.add_argument('--source-run',required=True);p.add_argument('--successor-run',required=True);p.add_argument('--reason',required=True)
        if name in {'propose','review'}:p.add_argument('--input',required=True)
        if name in {'approve','reject'}:p.add_argument('--proposal-hash',required=True)
        if name in {'reject','abandon'}:p.add_argument('--reason',required=True)
        if name=='abandon':p.add_argument('--disposition',required=True,choices=['keep-paused','resume-source','cancel-source'])
    register=sub.add_parser('register-executor');register.add_argument('--run-id',required=True);register.add_argument('--agent-id',required=True)
    group=register.add_mutually_exclusive_group(required=True);group.add_argument('--pid',type=int);group.add_argument('--handle')
    receipt=sub.add_parser('executor-receipt');receipt.add_argument('--run-id',required=True);receipt.add_argument('--agent-id',required=True);receipt.add_argument('--handle',required=True);receipt.add_argument('--input',required=True)
    advance=sub.add_parser('advance-adoptions');advance.add_argument('--run-id',required=True);advance.add_argument('--action-id',required=True)
    args=parser.parse_args(argv)
    if args.operation=='advance-adoptions':return RunStore(root,args.run_id).advance_adoptions(args.action_id)
    if args.operation in {'register-executor','executor-receipt'}:
        from cogito_execution_registry import register_process,register_external,record_external_receipt,snapshot
        with project_lock(root):
            source=RunStore(root,args.run_id);tasks=source.load()['tasks']
            if not any(t.get('agent_id')==args.agent_id for t in tasks.values()):
                raise CogitoError('executor must match a recorded Worker lease')
            if args.operation=='register-executor':
                check_run_fence(root,args.run_id,'register-executor')
                if args.pid is not None:register_process(root,args.run_id,args.agent_id,args.pid)
                else:register_external(root,args.run_id,args.agent_id,args.handle)
            else:
                record_external_receipt(root,args.run_id,args.agent_id,args.handle,load_json(Path(args.input)))
            return snapshot(root,args.run_id,allow_external_receipts=True)
    store=ReplanStore(root,args.replan_id)
    op=args.operation
    if op=='status':return store.load()
    if op=='begin':return store.begin(args.source_run,args.successor_run,args.reason,args.action_id)
    if op=='stop':return store.stop(args.action_id)
    if op=='propose':return store.propose(load_json(Path(args.input)),args.action_id)
    if op=='review':return store.review(load_json(Path(args.input)),args.action_id)
    if op=='approve':return store.approve(args.proposal_hash,args.action_id)
    if op=='reject':return store.reject(args.proposal_hash,args.reason,args.action_id)
    if op=='handoff':return store.handoff(args.action_id)
    return store.abandon(args.disposition,args.reason,args.action_id)
