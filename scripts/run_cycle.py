"""Pull the inbox doc and process everything new."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kiln import ingest, store

text = Path(sys.argv[1]).read_text(encoding="utf-8")
conn = store.connect()
pending = ingest.new_items(text, conn)
n = sum(len(p.get("urls") or []) for p in pending)
print("new lines: %d  ->  %d urls" % (len(pending), n), flush=True)
t0 = time.time()
for r in ingest.ingest_text(text, source="gdoc", conn=conn):
    print("  [%5.0fs] %-58s %s" % (time.time()-t0, (r.get("url") or r.get("note_only",""))[:58],
                                   (r.get("title") or r.get("status",""))[:58]), flush=True)
c = store.counts(conn)
print("\ntotal items: %d | est at paid rates: $%.4f" % (c["total"], c["spend"]))
print("by action:", c["by_action"])
conn.close()
