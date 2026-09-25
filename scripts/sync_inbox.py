"""Ingest an inbox document, then follow up on what came in.

Kiln never edits your doc - it hashes each line and remembers what it has
already processed, so re-running is always safe. The follow-up is the same
one the scheduled sync runs (kiln/brain.py), so a hand-run sync ends up in
the same place.

    python scripts/sync_inbox.py inbox.txt
    cat inbox.txt | python scripts/sync_inbox.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiln import brain, ingest, store


def main() -> int:
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
        print("  nothing new - every line already processed")
        conn.close()
        return 0

    results = ingest.ingest_text(text, source="gdoc", conn=conn)
    for r in results:
        print("  ->", json.dumps(r, ensure_ascii=False)[:160])
    print("\nfollowing up:")
    print(brain.render(brain.sweep(conn=conn)))
    counts = store.counts(conn)
    counts.pop("sections", None)
    print("\ncounts:", json.dumps(counts))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
