"""Model router: one call site, several providers, automatic fallback.

Policy lives in config.py and the registry, this is just the mechanism.
A few things it works around: the free tier 429s without warning, qwen3-vl
puts its answer in `thinking` instead of `response` under format=json, and
local models sometimes run away and need their JSON repaired.
"""
from __future__ import annotations

import base64
import json
import re
import time
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from . import config

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ModelResult:
    ok: bool
    data: Any = None                 # parsed JSON when a schema was asked for
    text: str = ""                   # raw text
    provider: str = ""
    model: str = ""
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0
    error: str = ""
    attempts: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


# ---------------------------------------------------------------------------
# Daily quota ledger (survives restarts; resets at local midnight)
# ---------------------------------------------------------------------------
_LEDGER_PATH = config.DATA / "quota.json"
_lock = threading.Lock()


def _load_ledger() -> dict:
    today = date.today().isoformat()
    try:
        d = json.loads(_LEDGER_PATH.read_text(encoding="utf-8"))
        if d.get("day") == today:
            return d
    except Exception:
        pass
    return {"day": today, "counts": {}, "spend_usd": 0.0}


def _save_ledger(d: dict) -> None:
    try:
        _LEDGER_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


def quota_snapshot() -> dict:
    """What the UI shows in the cost meter."""
    with _lock:
        d = _load_ledger()
        used = d["counts"]
        return {
            "day": d["day"],
            "spend_usd": round(d.get("spend_usd", 0.0), 4),
            "models": [
                {
                    "model": m,
                    "used": used.get(m, 0),
                    "budget": b,
                    "left": max(0, b - used.get(m, 0)),
                }
                for m, b in config.FREE_TIER_RPD.items()
            ],
        }


def _budget_left(model: str) -> bool:
    budget = config.FREE_TIER_RPD.get(model)
    if budget is None:
        return True
    with _lock:
        return _load_ledger()["counts"].get(model, 0) < budget


def _record(model: str, cost: float) -> None:
    with _lock:
        d = _load_ledger()
        d["counts"][model] = d["counts"].get(model, 0) + 1
        d["spend_usd"] = d.get("spend_usd", 0.0) + cost
        _save_ledger(d)


def _burn(model: str) -> None:
    """Mark a model as exhausted for today after a hard 429."""
    with _lock:
        d = _load_ledger()
        d["counts"][model] = config.FREE_TIER_RPD.get(model, 10**6)
        _save_ledger(d)


# ---------------------------------------------------------------------------
# JSON extraction / repair
# ---------------------------------------------------------------------------
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_loose(raw: str) -> Any | None:
    """Best-effort JSON out of a model response.

    Handles: clean JSON, fenced JSON, prose-wrapped JSON, and truncated
    JSON (a runaway generation that hit the token ceiling mid-object).
    """
    if not raw:
        return None
    raw = raw.strip()
    for candidate in (raw, *(m.group(1).strip() for m in _FENCE.finditer(raw))):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # first {...} or [...] block
    start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
    if start < 0:
        return None
    frag = raw[start:]
    try:
        return json.loads(frag)
    except Exception:
        pass
    # truncated: close whatever is open, dropping a trailing partial token
    depth_c = depth_s = 0
    in_str = esc = False
    cut = None
    for i, ch in enumerate(frag):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth_c += 1
        elif ch == "}":
            depth_c -= 1
        elif ch == "[":
            depth_s += 1
        elif ch == "]":
            depth_s -= 1
        if depth_c == 0 and depth_s == 0 and i > 0:
            cut = i + 1
    if cut:
        try:
            return json.loads(frag[:cut])
        except Exception:
            pass
    patched = frag
    if in_str:
        patched += '"'
    patched = patched.rstrip().rstrip(",")
    patched += "]" * max(0, depth_s) + "}" * max(0, depth_c)
    try:
        return json.loads(patched)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def redact(text: str) -> str:
    """Strip anything key-shaped before it gets stored or displayed."""
    if not text:
        return text
    for secret in filter(None, (config.GEMINI_API_KEY,)):
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    # Generic shapes: Google AIza..., OpenAI sk-..., and any ?key=/&key= pair
    text = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "[redacted]", text)
    text = re.sub(r"\bsk-[0-9A-Za-z_\-]{10,}", "[redacted]", text)
    text = re.sub(r"([?&](?:key|api_key|access_token)=)[^&\s\"']+", r"\1[redacted]", text)
    return text


def _post(url: str, payload: dict, timeout: int,
          headers: dict | None = None) -> tuple[dict | None, str]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:400]
        except Exception:
            body = ""
        return None, redact(f"HTTP {e.code} {body}")
    except Exception as e:
        return None, redact(f"{type(e).__name__}: {str(e)[:250]}")


def _mime_for(p: Path) -> str:
    s = p.suffix.lower()
    return {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        ".wav": "audio/wav", ".ogg": "audio/ogg",
    }.get(s, "application/octet-stream")


def _is_video(p: Path) -> bool:
    return p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi"}


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
def _call_gemini(model: str, prompt: str, media: list[Path], *,
                 grounded: bool, thinking: int, want_json: bool,
                 timeout: int) -> ModelResult:
    if not config.GEMINI_API_KEY:
        return ModelResult(False, error="GEMINI_API_KEY not set",
                           provider="gemini", model=model)
    budget_key = model + "#grounded" if grounded else model
    if not _budget_left(budget_key):
        return ModelResult(False, error="daily free-tier budget spent",
                           provider="gemini_grounded" if grounded else "gemini",
                           model=model)

    parts: list[dict] = [{"text": prompt}]
    for p in media:
        parts.append({"inlineData": {"mimeType": _mime_for(p),
                                     "data": base64.b64encode(p.read_bytes()).decode()}})

    gen: dict[str, Any] = {"temperature": 0.15}
    if want_json and not grounded:
        # Grounded calls cannot also force a JSON mime type.
        gen["responseMimeType"] = "application/json"
    if any(_is_video(p) or p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} for p in media):
        gen["mediaResolution"] = "MEDIA_RESOLUTION_HIGH"
    if thinking:
        gen["thinkingConfig"] = {"thinkingBudget": thinking}

    payload: dict[str, Any] = {"contents": [{"parts": parts}], "generationConfig": gen}
    if grounded:
        payload["tools"] = [{"google_search": {}}]

    # Key in a header, not the query string, so it stays out of logs.
    url = f"{config.GEMINI_BASE}/models/{model}:generateContent"
    auth = {"x-goog-api-key": config.GEMINI_API_KEY}

    t0 = time.time()
    # 503 is transient, retry it. 429 is quota, drop to the next rung.
    out, err = _post(url, payload, timeout, auth)
    for backoff in (4, 9):
        if out is not None or "HTTP 503" not in err:
            break
        time.sleep(backoff)
        out, err = _post(url, payload, timeout, auth)
    secs = time.time() - t0

    if out is None:
        if "HTTP 429" in err:
            # Grounded search has its own much smaller quota, so don't let a
            # grounded 429 burn the budget for plain calls on the same model.
            _burn(model + "#grounded" if grounded else model)
        # A rejected mediaResolution is recoverable: retry at default res.
        if "mediaResolution" in err and "HTTP 400" in err:
            gen.pop("mediaResolution", None)
            out, err = _post(url, payload, timeout, auth)
            secs = time.time() - t0
        if out is None:
            return ModelResult(False, error=err, provider="gemini",
                               model=model, seconds=secs)

    u = out.get("usageMetadata", {}) or {}
    tin = u.get("promptTokenCount", 0)
    tout = u.get("candidatesTokenCount", 0)
    tthink = u.get("thoughtsTokenCount", 0)
    ip, op = config.PRICES.get(model, (0.0, 0.0))
    cost = tin * ip / 1e6 + (tout + tthink) * op / 1e6

    text = ""
    citations: list[dict] = []
    try:
        cand = out["candidates"][0]
        for part in cand["content"]["parts"]:
            if "text" in part:
                text += part["text"]
        gm = cand.get("groundingMetadata") or {}
        for chunk in gm.get("groundingChunks", []) or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                citations.append({"url": web["uri"], "title": web.get("title", "")})
    except Exception:
        return ModelResult(False, error="no candidate text", provider="gemini",
                           model=model, seconds=secs, tokens_in=tin, tokens_out=tout)

    _record(model, cost)
    data = parse_json_loose(text) if want_json else None
    if want_json and data is None:
        return ModelResult(False, text=text, error="unparseable JSON",
                           provider="gemini", model=model, seconds=secs,
                           tokens_in=tin, tokens_out=tout, thinking_tokens=tthink,
                           cost_usd=cost)
    return ModelResult(True, data=data, text=text, provider="gemini", model=model,
                       seconds=secs, tokens_in=tin, tokens_out=tout,
                       thinking_tokens=tthink, cost_usd=cost, citations=citations)


def _call_ollama(model: str, prompt: str, media: list[Path], *,
                 want_json: bool, timeout: int, cloud: bool) -> ModelResult:
    images: list[str] = []
    for p in media:
        if _is_video(p):
            # Measured: local VLMs cannot read video. Caller must pass frames.
            return ModelResult(
                False, provider="ollama_cloud" if cloud else "ollama", model=model,
                error="local/ollama path cannot read video; extract frames first",
            )
        images.append(base64.b64encode(p.read_bytes()).decode())

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.15, "num_ctx": 16384},
    }
    if images:
        payload["images"] = images
    if want_json:
        payload["format"] = "json"

    t0 = time.time()
    out, err = _post(f"{config.OLLAMA_HOST}/api/generate", payload, timeout)
    secs = time.time() - t0
    prov = "ollama_cloud" if cloud else "ollama"
    if out is None:
        return ModelResult(False, error=err, provider=prov, model=model, seconds=secs)

    # THE qwen3-vl GOTCHA: with format=json the answer can land in `thinking`
    # while `response` comes back empty. Measured, not theoretical.
    text = (out.get("response") or "").strip() or (out.get("thinking") or "").strip()
    tin = out.get("prompt_eval_count", 0) or 0
    tout = out.get("eval_count", 0) or 0

    data = parse_json_loose(text) if want_json else None
    if want_json and data is None:
        return ModelResult(False, text=text, error=f"unparseable JSON ({len(text)} ch)",
                           provider=prov, model=model, seconds=secs,
                           tokens_in=tin, tokens_out=tout)
    return ModelResult(True, data=data, text=text, provider=prov, model=model,
                       seconds=secs, tokens_in=tin, tokens_out=tout, cost_usd=0.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate(task: str, prompt: str, media: list[Path] | None = None, *,
             want_json: bool = True, timeout: int = 600,
             ladder: list[tuple[str, str]] | None = None) -> ModelResult:
    """Run `task` down its ladder until something works.

    task: one of config.LADDERS ("extract", "extract_deep", "classify",
          "research", "reason"). Unknown tasks fall back to "classify".
    """
    from . import providers, registry, secrets_store

    media = [Path(m) for m in (media or [])]
    # The registry is the source of truth: the UI's ordering IS the priority,
    # and config.LADDERS is only the seed it was built from.
    steps = ladder or registry.ladder_for(task) or config.LADDERS.get(task) \
        or config.LADDERS["classify"]
    thinking = registry.thinking_for(task)
    attempts: list[str] = []
    last = ModelResult(False, error="no providers configured")

    for provider, model in steps:
        base = provider.replace("_grounded", "")
        spec = providers.PROVIDER_SPECS.get(base, {})

        # Skip a rung that structurally cannot serve this request, rather than
        # spending a call to discover it. Measured: local VLMs cannot read
        # video at all, and a text-only model cannot read a carousel.
        ok, why = providers.can_serve(base, media, registry.caps_for(base, model))
        if not ok:
            attempts.append(f"{provider}:{model} skipped ({why})")
            continue

        key_ref = spec.get("key_ref") or ""
        api_key = secrets_store.get_key(key_ref) if key_ref else ""
        if spec.get("needs_key") and not api_key:
            attempts.append(f"{provider}:{model} skipped (no API key)")
            continue

        adapter = spec.get("adapter", "")
        if provider in ("gemini", "gemini_grounded"):
            res = _call_gemini(model, prompt, media,
                               grounded=(provider == "gemini_grounded"),
                               thinking=thinking, want_json=want_json,
                               timeout=timeout)
        elif provider in ("ollama", "ollama_cloud"):
            res = _call_ollama(model, prompt, media, want_json=want_json,
                               timeout=timeout, cloud=(provider == "ollama_cloud"))
        elif adapter in ("openai_compatible", "anthropic"):
            fn = (providers.call_openai_compatible if adapter == "openai_compatible"
                  else providers.call_anthropic)
            raw = fn(model, prompt, media,
                     base_url=spec.get("base_url", ""), api_key=api_key,
                     want_json=want_json, timeout=timeout)
            pin, pout = registry.price_for(model)
            cost = (raw.get("tokens_in", 0) * pin / 1e6
                    + raw.get("tokens_out", 0) * pout / 1e6)
            data = parse_json_loose(raw.get("text", "")) if want_json else None
            res = ModelResult(
                ok=bool(raw.get("ok")) and (data is not None or not want_json),
                data=data, text=raw.get("text", ""), provider=provider, model=model,
                seconds=raw.get("seconds", 0.0), tokens_in=raw.get("tokens_in", 0),
                tokens_out=raw.get("tokens_out", 0), cost_usd=cost,
                error=redact(raw.get("error", "") or
                             ("unparseable JSON" if want_json and data is None else "")),
            )
            if res.ok:
                _record(model, cost)
        else:
            attempts.append(f"{provider}:{model} skipped (unknown provider)")
            continue

        attempts.append(f"{provider}:{model} " + ("ok" if res.ok else f"FAIL {res.error[:90]}"))
        if res.ok:
            res.attempts = attempts
            return res
        last = res

    last.attempts = attempts
    return last


def health() -> dict:
    """Which rungs are actually reachable right now. Shown on the UI status bar."""
    out: dict[str, Any] = {"gemini": False, "ollama": False, "models": [], "quota": quota_snapshot()}
    if config.GEMINI_API_KEY:
        d, err = _post(
            f"{config.GEMINI_BASE}/models/gemini-3.5-flash-lite:generateContent",
            {"contents": [{"parts": [{"text": "ping"}]}],
             "generationConfig": {"maxOutputTokens": 1}},
            30,
            {"x-goog-api-key": config.GEMINI_API_KEY},
        )
        out["gemini"] = d is not None or "HTTP 429" in err
        out["gemini_detail"] = "ok" if d is not None else err[:120]
    try:
        req = urllib.request.Request(f"{config.OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=8) as r:
            tags = json.loads(r.read().decode())
        out["ollama"] = True
        out["models"] = sorted(m["name"] for m in tags.get("models", []))
    except Exception as e:
        out["ollama_detail"] = str(e)[:120]
    return out
