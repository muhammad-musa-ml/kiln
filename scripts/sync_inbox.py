"""Research a directory of Muse README dossiers without publishing or cleanup.

    python scripts/sync_inbox.py data/research/incoming

Use scripts/daily.py for the full scheduled flow. Direct URL intake is an
explicit compatibility option: --legacy-links inbox.txt. Drive/Doc cleanup
belongs to the authenticated connector after exact live verification.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiln import brain, ingest, pipeline, store


def main() -> int:
    if '--legacy-links' not in sys.argv:
        from kiln import readme
        folder=Path(sys.argv[1]) if len(sys.argv)>1 else readme.INCOMING
        if not folder.is_dir():
            print('Expected a README directory. Archived URL intake requires --legacy-links.');return 2
        results=readme.import_folder(folder)
        print(json.dumps(results,ensure_ascii=False,indent=2))
        return int(any(r.get('error') for r in results))
    sys.argv.remove('--legacy-links')
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    conn = store.connect()
    pending = ingest.new_items(text, conn)
    print(f"parsed: {len(ingest.parse_doc(text))} lines  |  new: {len(pending)}")
    for p in pending:
        print("  NEW", (p.get("url") or p.get("note", ""))[:88])
    if not pending:
        print("  nothing new - every link already read")

    # Not skipped when nothing is new: an instruction added under an old
    # link, a failed read due another try, or an item still waiting for its
    # follow-up all need this pass just the same.
    results = ingest.ingest_text(text, source="gdoc", conn=conn)
    for r in results:
        print("  ->", json.dumps(r, ensure_ascii=False)[:160])
    for it in pipeline.retry_failed(conn):
        print("  retried", (it.get("url") or "")[:70],
              "failed again" if it.get("error") else (it.get("title") or "")[:40])
    print("\nfollowing up:")
    print(brain.render(brain.sweep(conn=conn)))
    counts = store.counts(conn)
    counts.pop("sections", None)
    print("\ncounts:", json.dumps(counts))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
