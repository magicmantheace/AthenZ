"""AthenZ CLI: explicit owner review controls and scoped coding commands."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .learning import LearningStore
from .store import KINDS


def private_export(path: Path, obj) -> None:
    dest = path.expanduser().resolve()
    if dest.exists():
        raise FileExistsError('Refusing to overwrite export')
    if not dest.parent.is_dir():
        raise ValueError('Export parent directory must exist')
    # Never accidentally emit private data inside a Git working tree.
    if any((p / '.git').exists() for p in (dest.parent, *dest.parents)):
        raise ValueError('Private export cannot be written inside a Git repository')
    dest.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        dest.chmod(0o600)
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='athenz', description='Local-first identity, learning and reviewed code proposals')
    p.add_argument('--home', type=Path, help='Private data directory')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('init')
    x = sub.add_parser('propose')
    x.add_argument('kind', choices=sorted(KINDS))
    x.add_argument('text')
    x.add_argument('--source', default='owner:cli')
    x.add_argument('--source-ref', default='')
    x.add_argument('--confidence', type=float, default=1.0)
    x = sub.add_parser('status')
    x.add_argument('id', type=int)
    x.add_argument('state', choices=['approved', 'pending', 'rejected'])
    x = sub.add_parser('revise')
    x.add_argument('id', type=int)
    x.add_argument('text')
    x.add_argument('--reason', required=True)
    x = sub.add_parser('forget')
    x.add_argument('table', choices=['identity', 'decisions', 'writing_samples'])
    x.add_argument('id', type=int)
    x = sub.add_parser('forget-runtime')
    x.add_argument('table', choices=['messages', 'feedback', 'train_pairs', 'proposals', 'test_runs', 'experiences'])
    x.add_argument('id', type=int)
    x = sub.add_parser('delete-session')
    x.add_argument('session')
    x = sub.add_parser('purge-source')
    x.add_argument('source')
    x.add_argument('--source-ref', default='')
    x = sub.add_parser('list')
    x.add_argument('table', choices=['identity', 'decisions', 'writing_samples', 'events',
       'identity_revisions', 'messages', 'feedback', 'train_pairs', 'proposals', 'test_runs', 'experiences'])
    x.add_argument('--status', choices=['approved', 'pending', 'rejected'])
    x = sub.add_parser('decision')
    x.add_argument('scenario')
    x.add_argument('choice')
    x.add_argument('rationale')
    x.add_argument('--exception', default='')
    x.add_argument('--source', default='owner:cli')
    x.add_argument('--source-ref', default='')
    x.add_argument('--option', dest='options', action='append', help='Repeat for each explicit choice')
    x.add_argument('--split', choices=['train', 'calibration', 'test'], default='train')
    x = sub.add_parser('decision-status')
    x.add_argument('id', type=int)
    x.add_argument('state', choices=['approved', 'pending', 'rejected'])
    x = sub.add_parser('sample')
    x.add_argument('text')
    x.add_argument('--source', default='owner:cli')
    x = sub.add_parser('review')
    x.add_argument('table', choices=['writing_samples', 'train_pairs', 'experiences'])
    x.add_argument('id', type=int)
    x.add_argument('state', choices=['approved', 'pending', 'rejected'])
    x = sub.add_parser('feedback')
    x.add_argument('message_id', type=int)
    x.add_argument('rating', choices=['up', 'down'])
    x.add_argument('--correction', default='')
    x = sub.add_parser('import-chatgpt')
    x.add_argument('path', type=Path)
    x.add_argument('--source-ref', required=True)
    x.add_argument('--limit', type=int, default=500)
    x.add_argument('--confirm', action='store_true', help='Explicitly store previewed samples as pending')
    x = sub.add_parser('export')
    x.add_argument('path', type=Path)
    x = sub.add_parser('export-training')
    x.add_argument('path', type=Path)
    x = sub.add_parser('evaluate-decisions')
    x.add_argument('--split', choices=['calibration', 'test'], default='test')
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--seed', type=int, default=42)
    x.add_argument('--report', type=Path, help='Optional private report, stored outside Git')
    sub.add_parser('context')
    x = sub.add_parser('code-propose')
    x.add_argument('repo', type=Path)
    x.add_argument('task')
    x.add_argument('files', nargs='+')
    x = sub.add_parser('code-diff')
    x.add_argument('id', type=int)
    for cmd in ('code-apply', 'code-undo'):
        x = sub.add_parser(cmd)
        x.add_argument('id', type=int)
    x = sub.add_parser('code-test')
    x.add_argument('id', type=int)
    x.add_argument('--kind', choices=['compile', 'unittest'], default='compile')
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    store = LearningStore(args.home)
    try:
        if args.cmd == 'init':
            print(f'Initialized private AthenZ store at {store.path}')
        elif args.cmd == 'propose':
            print(f'Pending identity #{store.propose(args.kind, args.text, source=args.source, source_ref=args.source_ref, confidence=args.confidence)}')
        elif args.cmd == 'status':
            print('Updated' if store.status(args.id, args.state) else 'Unknown ID')
        elif args.cmd == 'revise':
            print('Revision pending approval' if store.revise(args.id, args.text, args.reason) else 'Unknown ID')
        elif args.cmd == 'forget':
            print('Deleted' if store.delete(args.table, args.id) else 'Unknown ID')
        elif args.cmd == 'forget-runtime':
            print('Deleted' if store.forget_runtime(args.table, args.id) else 'Unknown ID')
        elif args.cmd == 'delete-session':
            print(f'Deleted {store.delete_session(args.session)} messages and linked feedback')
        elif args.cmd == 'purge-source':
            print(json.dumps(store.purge_source(args.source, args.source_ref)))
        elif args.cmd == 'list':
            print(json.dumps(store.list_items(args.table, args.status), indent=2))
        elif args.cmd == 'decision':
            print(f'Pending decision #{store.add_decision(args.scenario, args.choice, args.rationale, source=args.source, source_ref=args.source_ref, exception=args.exception,
                options=args.options, split=args.split)}')
        elif args.cmd == 'decision-status':
            print('Updated' if store.decision_status(args.id, args.state) else 'Unknown ID')
        elif args.cmd == 'sample':
            print(f'Pending sample #{store.add_sample(args.text, source=args.source)}')
        elif args.cmd == 'review':
            print('Updated' if store.set_review(args.table, args.id, args.state) else 'Unknown ID')
        elif args.cmd == 'feedback':
            print(f'Feedback #{store.add_feedback(args.message_id, args.rating, args.correction)}; examples require separate approval')
        elif args.cmd == 'import-chatgpt':
            from .importers import parse_chatgpt_export, import_samples
            examples = parse_chatgpt_export(args.path, args.limit)
            if args.confirm:
                print(f'Imported {import_samples(store, examples, "chatgpt:export", args.source_ref)} pending writing samples')
            else:
                print(f'Preview: {len(examples)} owner-authored writing samples; no data stored. Run with --confirm to import.')
        elif args.cmd == 'export':
            private_export(args.path, store.export())
            print(f'Private archive written to {args.path}')
        elif args.cmd == 'export-training':
            pairs = store.approved_training_pairs()
            private_export(args.path, pairs)
            print(f'Exported {len(pairs)} approved training pairs to {args.path}')
        elif args.cmd == 'evaluate-decisions':
            from .evaluation import evaluate_decisions
            from .chat import OllamaClient
            result = evaluate_decisions(store, OllamaClient(), split=args.split, limit=args.limit, seed=args.seed)
            if args.report:
                private_export(args.report, result)
            print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
        elif args.cmd == 'context':
            print(json.dumps(store.context(), indent=2))
        elif args.cmd == 'code-propose':
            from .chat import OllamaClient
            from .coding import propose
            pid = propose(store, OllamaClient(), str(args.repo), args.task, args.files)
            print(f'Proposal #{pid} saved. Review using: athenz code-diff {pid}')
        elif args.cmd in {'code-diff', 'code-apply', 'code-undo', 'code-test'}:
            from .coding import diff_for, change_status, run_tests
            if args.cmd == 'code-diff':
                print(diff_for(store, args.id))
            elif args.cmd == 'code-apply':
                print(f'Applied {change_status(store, args.id)} reviewed files')
            elif args.cmd == 'code-undo':
                print(f'Restored {change_status(store, args.id, undo=True)} files')
            elif args.cmd == 'code-test':
                code, output = run_tests(store, args.id, args.kind)
                print(f'Check exit {code}; evidence recorded as pending\n{output}')
    finally:
        store.close()


if __name__ == '__main__':
    main()
