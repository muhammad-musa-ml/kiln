"""Local web server. Stdlib only, no framework and no build step."""
from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, models, pipeline, store

# item_id -> {"stage":..., "started":..., "error":...}
JOBS: dict[str, dict] = {}

# File types a browser will run script from when opened directly.
_SCRIPTABLE = {"text/html", "application/xhtml+xml", "image/svg+xml",
               "text/xml", "application/xml"}
_jobs_lock = threading.Lock()


def _set_job(iid: str, **kw) -> None:
    with _jobs_lock:
        JOBS.setdefault(iid, {}).update(kw)


def _process_async(urls: list[str], **kw) -> list[str]:
    """Read every link on one line, then have Claude follow up on them together.

    One thread per line rather than per link, because an instruction on a
    line of several links is about the set, and the follow-up has to see
    all of them at once. What Claude adds lands on the item the same way it
    does in the scheduled sync, so localhost shows it without waiting.
    """
    from . import brain

    ids = [store.item_id(u) for u in urls]
    for iid, url in zip(ids, urls):
        _set_job(iid, stage="queued", started=time.time(), url=url, error="")

    def run():
        done = []
        for iid, url in zip(ids, urls):
            try:
                _set_job(iid, stage="working")
                pipeline.process_url(url, **kw)
                done.append(iid)
            except Exception as e:
                _set_job(iid, stage="error", error=f"{type(e).__name__}: {e}",
                         trace=traceback.format_exc()[-1500:], finished=time.time())
        if not done:
            return
        try:
            # KILN_BRAIN=0 turns the follow-up off here as well as in the sync.
            if config.BRAIN_ON:
                for iid in done:
                    _set_job(iid, stage="followup")
                brain.follow_up(done)
        finally:
            for iid in done:
                _set_job(iid, stage="done", finished=time.time())

    threading.Thread(target=run, daemon=True).start()
    return ids


class Handler(BaseHTTPRequestHandler):
    server_version = "Kiln"

    def log_message(self, fmt, *args):  # quiet
        pass

    # -- helpers -------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _host_ok(self) -> bool:
        """Only answer to this machine's own names for itself.

        The page at / carries the write token. A web page elsewhere cannot
        read it across origins, unless its domain is made to resolve to
        127.0.0.1, and then the browser calls it the same origin. The Host
        header still names that other domain, so it is refused here.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        allowed = {f"{h}:{config.PORT}" for h in ("127.0.0.1", "localhost", "[::1]")}
        allowed.add(f"{config.HOST}:{config.PORT}".lower())
        return host in allowed

    # -- routes --------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "unknown host"}, 421)
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        p = u.path

        try:
            if p in ("/", "/index.html"):
                html = (config.WEB / "index.html").read_bytes()
                if config.IS_LOCAL:
                    # Handed to the page at serve time, never written to the
                    # file on disk - so the static export cannot contain it.
                    inject = (
                        '<script>window.KILN_LOCAL=true;'
                        f'window.KILN_TOKEN="{config.LOCAL_TOKEN}";</script>'
                    ).encode()
                    html = html.replace(b"</head>", inject + b"</head>", 1)
                return self._send(200, html, "text/html")
            if p.startswith("/static/"):
                return self._file(config.WEB / p[len("/static/"):])
            if p.startswith("/media/"):
                rel = urllib.parse.unquote(p[len("/media/"):])
                target = (config.MEDIA / rel).resolve()
                # Segments, not text: a prefix test lets data/media-anything
                # pass as if it were inside data/media.
                if not target.is_relative_to(config.MEDIA.resolve()):
                    return self._json({"error": "forbidden"}, 403)
                return self._file(target, untrusted=True)
            if p.startswith("/artifacts/"):
                # Documents the follow-up made for an item. Same containment
                # rule as media: compare resolved paths, never the text.
                from . import artifacts
                rel = urllib.parse.unquote(p[len("/artifacts/"):])
                root = artifacts.ARTIFACTS.resolve()
                target = (root / rel).resolve()
                if target == root or not target.is_relative_to(root):
                    return self._json({"error": "forbidden"}, 403)
                return self._file(target, untrusted=True)

            if p == "/api/items":
                conn = store.connect()
                items = store.list_items(
                    conn, status=q.get("status", ""), action=q.get("action", ""),
                    topic=q.get("topic", ""), place=q.get("place", ""),
                    section=q.get("section", ""),
                    q=q.get("q", ""), urgent=q.get("urgent") == "1",
                    limit=int(q.get("limit", 200)))
                conn.close()
                with _jobs_lock:
                    jobs = dict(JOBS)
                return self._json({"items": items, "jobs": jobs})

            if p.startswith("/api/item/"):
                conn = store.connect()
                it = store.get_item(conn, p.rsplit("/", 1)[-1])
                conn.close()
                if it:
                    # Built by the publisher's own function, so the page shows
                    # the answer the same way here and on the site.
                    from . import jobs, publish
                    it["followup"] = publish.followup(it)
                    # The same prompt Queue it writes. Without it the page fell
                    # back to its own copy of the builder, which had drifted.
                    if ((it.get("enrich") or {}).get("project") or {}).get("name"):
                        it["build_prompt"] = jobs.build_prompt(it)
                    # How it was made, for the local page only. Neutral names,
                    # because the page is the same file the site publishes.
                    c = it.get("claude") or {}
                    it["fu_local"] = {"state": it.get("claude_state") or "",
                                      **{k: c.get(k) for k in (
                                          "verdict", "why", "missing", "planner",
                                          "tasks", "final", "last_error")}}
                return self._json(it or {"error": "not found"}, 200 if it else 404)

            if p == "/api/facets":
                conn = store.connect()
                c = store.counts(conn)
                conn.close()
                return self._json(c)

            if p == "/api/health":
                h = models.health()
                h["ollama_host"] = config.OLLAMA_HOST
                h["policy"] = config.POLICY
                return self._json(h)

            if p == "/api/jobs":
                with _jobs_lock:
                    return self._json(dict(JOBS))

            if p == "/api/models":
                # Local only: it names which providers hold credentials.
                if not config.IS_LOCAL:
                    return self._json({"error": "not found"}, 404)
                from . import registry
                return self._json(registry.overview())

            if p == "/api/build/pending":
                if not config.IS_LOCAL:
                    return self._json({"error": "not found"}, 404)
                from . import jobs
                return self._json({"pending": jobs.pending()})

            if p == "/api/questions":
                if not config.IS_LOCAL:
                    return self._json({"error": "not found"}, 404)
                from . import questions
                return self._json({"open": questions.open_questions()})

            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}",
                               "trace": traceback.format_exc()[-1200:]}, 500)

    def _authorised(self) -> bool:
        """Every write route requires the local token.

        Constant-time compare so a timing oracle cannot recover it byte by
        byte. Loopback alone is not an authorisation boundary.
        """
        import hmac

        sent = (self.headers.get("X-Kiln-Token") or "").strip()
        if not sent:
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                sent = auth[7:].strip()
        return bool(sent) and hmac.compare_digest(sent, config.LOCAL_TOKEN)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path

        if not config.IS_LOCAL:
            return self._json({"error": "this deployment is read-only"}, 405)
        if not self._host_ok():
            return self._json({"error": "unknown host"}, 421)
        if not self._authorised():
            # 404, not 401 - do not confirm the route exists.
            return self._json({"error": "not found"}, 404)

        b = self._body()
        try:
            if p == "/api/add":
                raw = (b.get("text") or b.get("url") or "").strip()
                if not raw:
                    return self._json({"error": "nothing to add"}, 400)
                from .ingest import parse_line
                added = []
                for line in raw.splitlines():
                    parsed = parse_line(line)
                    if not parsed or not parsed.get("url"):
                        continue
                    urls = parsed.get("urls") or [parsed["url"]]
                    # Same grouping as the inbox: several links on one line
                    # share a group tag, so the follow-up treats them as a set.
                    group = ["group:" + store.line_hash(line)[:8]] if len(urls) > 1 else []
                    added += _process_async(
                        urls, user_note=parsed.get("note", "") or b.get("note", ""),
                        user_do=parsed.get("do", "") or b.get("do", ""),
                        user_tags=(parsed.get("tags") or []) + group,
                        urgent=parsed.get("urgent", False) or bool(b.get("urgent")),
                        deadline=parsed.get("by", ""), source="manual")
                if not added:
                    return self._json({"error": "no link found in that text"}, 400)
                return self._json({"queued": added})

            if p == "/api/status":
                conn = store.connect()
                conn.execute("UPDATE items SET status=?, updated_at=? WHERE id=?",
                             (b.get("status", "triage"), time.time(), b.get("id")))
                conn.commit()
                it = store.get_item(conn, b.get("id"))
                conn.close()
                return self._json(it or {})

            if p == "/api/urgent":
                conn = store.connect()
                conn.execute("UPDATE items SET urgent=?, updated_at=? WHERE id=?",
                             (1 if b.get("urgent") else 0, time.time(), b.get("id")))
                conn.commit()
                conn.close()
                return self._json({"ok": True})

            if p == "/api/reprocess":
                iid = b.get("id")
                conn = store.connect()
                it = store.get_item(conn, iid)
                conn.close()
                if not it:
                    return self._json({"error": "not found"}, 404)
                _process_async([it["url"]], user_note=it.get("user_note") or "",
                               user_do=it.get("user_do") or "",
                               urgent=bool(it.get("urgent")), force=True,
                               source=it.get("source") or "manual")
                return self._json({"queued": iid})

            if p == "/api/run":
                return self._run_command(b)

            # ---- build jobs ---------------------------------------------
            if p == "/api/build":
                from . import jobs
                j = jobs.create(b.get("id", ""), target=b.get("target", "copy"),
                                repo_name=b.get("repo_name", ""),
                                directory=b.get("directory", ""))
                if j.get("error"):
                    return self._json(j, 404)
                return self._json(j)

            if p == "/api/build/complete":
                from . import jobs
                return self._json({"ok": jobs.complete(b.get("job_id", ""),
                                                       b.get("note", ""))})

            if p == "/api/questions/answer":
                from . import questions
                picked = [str(x) for x in (b.get("picked") or []) if str(x).strip()]
                r = questions.answer(b.get("id", ""), b.get("choice", ""),
                                     b.get("note", ""), picked=picked)
                return self._json(r, 404 if r.get("error") else 200)

            # ---- model management ---------------------------------------
            if p.startswith("/api/models/"):
                from . import providers, registry, secrets_store
                what = p.rsplit("/", 1)[-1]

                if what == "test":
                    # Fire a REAL call before anything is saved. A model that
                    # cannot answer is not added.
                    res = providers.test_model(
                        b.get("provider", ""), b.get("model", ""),
                        api_key=b.get("api_key", ""), base_url=b.get("base_url", ""))
                    return self._json(res)

                if what == "add":
                    prov, model = b.get("provider", ""), b.get("model", "")
                    if not prov or not model:
                        return self._json({"error": "provider and model required"}, 400)
                    key = (b.get("api_key") or "").strip()
                    spec = providers.PROVIDER_SPECS.get(prov, {})
                    # Verify FIRST, save the key only once it works.
                    res = providers.test_model(prov, model, api_key=key,
                                               base_url=b.get("base_url", ""))
                    if not res.get("ok"):
                        return self._json({"error": res.get("error", "test failed"),
                                           "tested": res}, 400)
                    if key and spec.get("key_ref"):
                        secrets_store.set_key(spec["key_ref"], key)
                    m = registry.add_model(
                        prov, model, label=b.get("label", ""),
                        caps=res.get("caps"),
                        free_rpd_=int(b.get("free_rpd") or 0), verified=True)
                    return self._json({"added": m, "tested": res})

                if what == "remove":
                    registry.remove_model(b.get("id", ""))
                    return self._json({"ok": True})

                if what == "enabled":
                    registry.set_enabled(b.get("id", ""), bool(b.get("enabled")))
                    return self._json({"ok": True})

                if what == "ladder":
                    registry.set_ladder(b.get("task", ""), b.get("ids") or [])
                    return self._json({"ok": True, "ladder": registry.ladder_for(b.get("task", ""))})

                if what == "thinking":
                    registry.set_thinking(b.get("task", ""), int(b.get("budget") or 0))
                    return self._json({"ok": True})

                if what == "forget_key":
                    secrets_store.delete_key(b.get("ref", ""))
                    return self._json({"ok": True})

            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}",
                               "trace": traceback.format_exc()[-1200:]}, 500)

    # -- the one-click runner -----------------------------------------
    def _run_command(self, b: dict):
        """Execute an install command - ONLY after re-validating it server-side.

        The UI already showed a preview, but the UI is not the gate: the
        allow-list is re-checked here so a crafted request cannot run
        something the preview never displayed.
        """
        # Second, independent gate. Shell execution is the single most
        # dangerous route in the app; it must be impossible outside local
        # mode even if some future refactor loosens the POST check above.
        if not config.IS_LOCAL:
            return self._json({"error": "not found"}, 404)

        iid = b.get("id", "")
        conn = store.connect()
        it = store.get_item(conn, iid)
        if not it:
            conn.close()
            return self._json({"error": "unknown item"}, 404)

        enr = it.get("enrich") or {}
        preview = enr.get("_install_preview") or {}
        cmd = (preview.get("command") or "").strip()
        if not cmd:
            conn.close()
            return self._json({"error": "this item has no install command"}, 400)
        if b.get("command") and b["command"].strip() != cmd:
            conn.close()
            return self._json({"error": "command does not match the stored preview"}, 400)
        if not preview.get("runnable"):
            conn.close()
            return self._json({"error": f"not runnable: {preview.get('reason')}"}, 400)

        base = preview.get("base", "")
        if base not in config.RUNNABLE_BINARIES:
            conn.close()
            return self._json({"error": f"'{base}' is not allow-listed"}, 400)
        low = cmd.lower()
        hit = [x for x in config.FORBIDDEN_PATTERNS if x in low]
        if hit:
            conn.close()
            return self._json({"error": f"blocked pattern: {hit}"}, 400)

        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                  timeout=900, cwd=str(config.ROOT))
            out = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-8000:]
            code = proc.returncode
        except subprocess.TimeoutExpired:
            out, code = "timed out after 900s", -1
        except Exception as e:
            out, code = f"{type(e).__name__}: {e}", -1

        conn.execute("INSERT INTO actions_log (item_id,command,exit_code,output,at)"
                     " VALUES (?,?,?,?,?)", (iid, cmd, code, out, time.time()))
        conn.commit()
        conn.close()
        return self._json({"exit_code": code, "output": out, "command": cmd})

    def _file(self, path: Path, untrusted: bool = False):
        if not path.exists() or not path.is_file():
            return self._json({"error": f"missing {path.name}"}, 404)
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        extra = {}
        if untrusted:
            # A saved post's media, or a document a model wrote after reading
            # one. An HTML file among them would otherwise run its scripts on
            # this origin, where the page carries the write token. Sandboxed,
            # it gets an origin of its own and no scripts. Only the kinds that
            # can carry a script get the sandbox: Chrome will not show a PDF
            # under one, and a PDF cannot touch this page anyway.
            extra = {"X-Content-Type-Options": "nosniff"}
            if ctype in _SCRIPTABLE:
                extra["Content-Security-Policy"] = "sandbox"
        self._send(200, path.read_bytes(), ctype, extra)


def serve():
    config.WEB.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print(f"\n  Kiln  ->  http://{config.HOST}:{config.PORT}")
    print(f"  db    ->  {config.DB_PATH}")
    print(f"  ollama->  {config.OLLAMA_HOST}")
    print("  ctrl-c to stop\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")


if __name__ == "__main__":
    serve()
