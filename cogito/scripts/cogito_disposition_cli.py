"""Public interface for cancellation and versioned outcome decisions."""
import argparse
from pathlib import Path

from cogito_common import load_json
from cogito_disposition_store import DispositionStore


def run(root, argv):
    parser = argparse.ArgumentParser(prog='cogito_gate.py disposition')
    sub = parser.add_subparsers(dest='operation', required=True)
    for name in ('status', 'history', 'begin', 'stop', 'propose', 'review', 'approve', 'reject', 'pause', 'release', 'complete'):
        item = sub.add_parser(name)
        item.add_argument('--disposition-id', required=True)
        if name not in {'status', 'history'}:
            item.add_argument('--action-id', required=True)
        if name == 'begin':
            item.add_argument('--source-run', required=True)
            item.add_argument('--reason', required=True)
            item.add_argument('--replan-id')
        if name in {'propose', 'review'}:
            item.add_argument('--input', required=True)
        if name == 'approve':
            item.add_argument('--proposal-hash', required=True)
            item.add_argument('--authorized', action='store_true', required=True)
        if name == 'complete':
            item.add_argument('--human-accepted', action='store_true')
        if name in {'reject', 'pause'}:
            item.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    store = DispositionStore(root, args.disposition_id)
    if args.operation == 'status':
        return store.load()
    if args.operation == 'history':
        from cogito_events import read_events
        return {'disposition_id': args.disposition_id, 'events': read_events(store.events_path)}
    if args.operation == 'begin':
        return store.begin(args.source_run, args.reason, args.action_id, replan_id=args.replan_id)
    if args.operation in {'propose', 'review'}:
        return getattr(store, args.operation)(load_json(Path(args.input)), args.action_id)
    if args.operation == 'approve':
        return store.approve(args.proposal_hash, args.authorized, args.action_id)
    if args.operation in {'reject', 'pause'}:
        return getattr(store, args.operation)(args.reason, args.action_id)
    if args.operation == 'complete':
        return store.complete(args.action_id, human_accepted=args.human_accepted)
    return getattr(store, args.operation)(args.action_id)
