"""Verify the audited public snapshot before issuing source-cleanup receipts."""
from __future__ import annotations

import concurrent.futures as cf
import http.client
import hashlib
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import config, readme

PUBLIC_URL = 'https://kiln-by-m.vercel.app'


def verify_public(out: Path = config.ROOT/'public', url: str = PUBLIC_URL, *, attempts=1) -> dict:
    out=Path(out)
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname:raise ValueError('Use the HTTPS public deployment URL')
    expected=json.loads((out/'data'/'items.json').read_text(encoding='utf-8'))
    def fetch(relative):
        req=urllib.request.Request(url.rstrip('/')+'/'+quote(relative,safe='/')+'?kiln_verify='+str(time.time_ns()),headers={'Cache-Control':'no-cache'})
        for retry in range(3):
            try:
                with urllib.request.urlopen(req,timeout=60) as response:return response.read()
            except (TimeoutError, OSError, http.client.IncompleteRead, urllib.error.URLError) as exc:
                if retry==2:raise ValueError('Unable to verify live file: '+relative) from exc
                time.sleep(retry+1)
    live=None
    for attempt in range(attempts):
        try:
            live=json.loads(fetch('data/items.json'))
            if live==expected:break
        except Exception:pass
        if attempt+1<attempts:
            print('Waiting for the audited deployment to appear…',flush=True);time.sleep(5)
    if live!=expected:raise ValueError('Live deployment differs from the current export; keep source files pending')
    # Vercel consumes its deployment config; it deliberately is not served.
    paths=[p for p in out.rglob('*') if p.is_file() and p.relative_to(out).as_posix()!='vercel.json']
    def check(path):
        relative=path.relative_to(out).as_posix()
        blob=fetch(relative)
        if hashlib.sha256(blob).digest()!=hashlib.sha256(path.read_bytes()).digest():
            raise ValueError('Live file differs: '+relative)
        return relative
    with cf.ThreadPoolExecutor(max_workers=8) as pool:verified=list(pool.map(check,paths))
    count=readme.mark_published(out,live_items=live)
    receipt={'verified_at':time.time(),'url':url,'topics':len(live['items']),'files':len(verified),
             'snapshot_sha256':hashlib.sha256((out/'data'/'items.json').read_bytes()).hexdigest(),'newly_published_documents':count}
    dest=config.DATA/'research'/'publication-receipt.json';dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt
