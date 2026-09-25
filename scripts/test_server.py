"""The local server: the prompt the page copies, the hosts it answers, and
the documents it serves.

A real server on a free port, against a throwaway data folder. Nothing here
touches the real library or starts any model.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="kiln-server-")).resolve()
os.environ["KILN_DATA"] = str(TMP)
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
os.environ["KILN_PORT"] = str(PORT)
os.environ["KILN_HOST"] = "127.0.0.1"

from kiln import config  # noqa: E402

if Path(config.DATA).resolve() != TMP or config.PORT != PORT:
    raise SystemExit("pins did not take: DATA=%s PORT=%s" % (config.DATA, config.PORT))

from kiln import artifacts, jobs, server, store  # noqa: E402

results: list[bool] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append(bool(passed))
    print(("  ok    " if passed else "  FAIL  ") + label
          + (("\n        " + detail) if detail and not passed else ""))


def get(path: str, host: str = "") -> tuple[int, dict, bytes]:
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 headers={"Host": host or "127.0.0.1:%d" % PORT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def main() -> int:
    conn = store.connect()
    store.upsert_item(conn, {
        "id": "p1", "url": "https://example.com/p1", "title": "A tool worth building",
        "processed_at": 1.0, "created_at": 1.0,
        "enrich_json": json.dumps({"project": {
            "name": "tiny-cli", "one_liner": "a small command line tool",
            "scope": "IN: parse a file. OUT: a web UI.", "stack": ["python"],
            "milestones": [{"step": "parse", "outcome": "it parses"}]}})})
    want = jobs.build_prompt(store.get_item(conn, "p1"))
    conn.close()

    doc = artifacts.ARTIFACTS / "p1"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    (doc / "notes.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        print("the prompt the page copies")
        code, _, body = get("/api/item/p1")
        got = json.loads(body or b"{}").get("build_prompt")
        check("an item with a brief comes with the prompt Queue it writes",
              code == 200 and got == want and len(want) > 200,
              "code %s, prompt %s chars" % (code, len(got or "")))

        print("the names it answers to")
        code, _, _ = get("/api/item/p1", host="localhost:%d" % PORT)
        check("localhost is this machine", code == 200, str(code))
        code, _, _ = get("/api/item/p1", host="kiln.attacker.example:%d" % PORT)
        check("any other name is refused, even on the right port", code == 421, str(code))

        print("documents a model wrote")
        code, h, _ = get("/artifacts/p1/page.html")
        check("an HTML document is served sandboxed, with no sniffing",
              code == 200 and h.get("Content-Security-Policy") == "sandbox"
              and h.get("X-Content-Type-Options") == "nosniff", str(h))
        code, h, _ = get("/artifacts/p1/notes.pdf")
        check("a PDF is not sandboxed, so the browser still shows it",
              code == 200 and "Content-Security-Policy" not in h, str(h))
        code, _, body = get("/artifacts/%2e%2e/kiln.db")
        check("a path out of the documents folder is refused",
              code in (403, 404) and b"SQLite" not in body, str(code))
    finally:
        srv.shutdown()
        srv.server_close()

    print()
    print("%d/%d pass" % (sum(results), len(results)))
    if all(results):
        shutil.rmtree(TMP, ignore_errors=True)
    else:
        print("test data kept for a look: %s" % TMP)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
