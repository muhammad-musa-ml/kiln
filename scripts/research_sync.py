"""README intake and receipt-based cloud cleanup handoff. No Drive credentials here."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kiln import readme, release, store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    intake=commands.add_parser('import');intake.add_argument('folder',nargs='?',default=str(readme.INCOMING));intake.add_argument('--stage-only',action='store_true')
    commands.add_parser('retry')
    verify=commands.add_parser('verify-live');verify.add_argument('--attempts',type=int,default=30)
    commands.add_parser('cleanup-plan')
    confirm=commands.add_parser('confirm-cleanup');confirm.add_argument('source_id');confirm.add_argument('digest')
    args=parser.parse_args()
    if args.command=='import':result=readme.import_folder(Path(args.folder),run=not args.stage_only)
    elif args.command=='retry':
        c=store.connect();pending=[r['source_id'] for r in c.execute("SELECT source_id FROM research_documents WHERE state='pending'")];c.close();result=[]
        for sid in pending:
            try:result.append(readme.process(sid))
            except Exception as exc:result.append({'source_id':sid,'error':str(exc)})
    elif args.command=='verify-live':result=release.verify_public(attempts=max(1,min(args.attempts,120)))
    elif args.command=='cleanup-plan':result=readme.cleanup_plan()
    else:readme.confirm_cleanup(args.source_id,digest=args.digest);result={'state':'cleaned','source_id':args.source_id}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(isinstance(result,list) and any(r.get('error') for r in result))


if __name__=='__main__':raise SystemExit(main())
