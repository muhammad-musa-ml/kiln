"""Provider adapters.

Four of them cover most things, since nearly everyone speaks OpenAI's wire
format by now. Each declares what it can handle so the router can skip a
model that can't do the job instead of wasting a call finding out.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import secrets_store

# ---------------------------------------------------------------------------
# Known providers. base_url is the OpenAI-compatible root where applicable.
# ---------------------------------------------------------------------------
PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "gemini": {
        "adapter": "gemini", "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_ref": "gemini", "needs_key": True,
        "signup": "https://aistudio.google.com/apikey",
        "caps": ["vision", "video", "json_mode", "thinking", "streaming"],
    },
    "ollama": {
        "adapter": "ollama", "label": "Ollama (local)",
        "base_url": "", "key_ref": "", "needs_key": False,
        "signup": "https://ollama.com/download",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "ollama_cloud": {
        "adapter": "ollama", "label": "Ollama Cloud",
        "base_url": "", "key_ref": "", "needs_key": False,
        "signup": "https://ollama.com/cloud",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "openai": {
        "adapter": "openai_compatible", "label": "OpenAI",
        "base_url": "https://api.openai.com/v1", "key_ref": "openai",
        "needs_key": True, "signup": "https://platform.openai.com/api-keys",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "groq": {
        "adapter": "openai_compatible", "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1", "key_ref": "groq",
        "needs_key": True, "signup": "https://console.groq.com/keys",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "openrouter": {
        "adapter": "openai_compatible", "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1", "key_ref": "openrouter",
        "needs_key": True, "signup": "https://openrouter.ai/keys",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "deepseek": {
        "adapter": "openai_compatible", "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1", "key_ref": "deepseek",
        "needs_key": True, "signup": "https://platform.deepseek.com/api_keys",
        "caps": ["json_mode", "streaming"],
    },
    "xai": {
        "adapter": "openai_compatible", "label": "xAI Grok",
        "base_url": "https://api.x.ai/v1", "key_ref": "xai",
        "needs_key": True, "signup": "https://console.x.ai",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "mistral": {
        "adapter": "openai_compatible", "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1", "key_ref": "mistral",
        "needs_key": True, "signup": "https://console.mistral.ai/api-keys",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "together": {
        "adapter": "openai_compatible", "label": "Together AI",
        "base_url": "https://api.together.xyz/v1", "key_ref": "together",
        "needs_key": True, "signup": "https://api.together.ai/settings/api-keys",
        "caps": ["vision", "json_mode", "streaming"],
    },
    "anthropic": {
        "adapter": "anthropic", "label": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1", "key_ref": "anthropic",
        "needs_key": True, "signup": "https://console.anthropic.com/settings/keys",
        "caps": ["vision", "json_mode", "thinking", "streaming"],
    },
    "custom": {
        "adapter": "openai_compatible", "label": "Custom (OpenAI-compatible)",
        "base_url": "", "key_ref": "custom", "needs_key": False,
        "signup": "", "caps": ["json_mode", "streaming"],
    },
}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def mime_for(p: Path) -> str:
    return {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".gif": "image/gif",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
    }.get(p.suffix.lower(), "application/octet-stream")


def media_kind(paths: list[Path]) -> str:
    if any(p.suffix.lower() in VIDEO_EXT for p in paths):
        return "video"
    if any(p.suffix.lower() in IMAGE_EXT for p in paths):
        return "image"
    return "text"


def can_serve(provider: str, paths: list[Path], caps: list[str] | None = None) -> tuple[bool, str]:
    """Would this provider structurally fail before we spend a call?"""
    caps = caps if caps is not None else (PROVIDER_SPECS.get(provider, {}).get("caps") or [])
    kind = media_kind(paths)
    if kind == "video" and "video" not in caps:
        return False, "cannot read video"
    if kind == "image" and "vision" not in caps:
        return False, "cannot read images"
    return True, ""


def _post(url: str, payload: dict, headers: dict, timeout: int) -> tuple[dict | None, str]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:400]
        except Exception:
            body = ""
        return None, f"HTTP {e.code} {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:250]}"


def _b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


# ---------------------------------------------------------------------------
# OpenAI-compatible  (/chat/completions)
# ---------------------------------------------------------------------------
def call_openai_compatible(model: str, prompt: str, media: list[Path], *,
                           base_url: str, api_key: str, want_json: bool,
                           timeout: int, extra_headers: dict | None = None) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}]
    for p in media:
        if p.suffix.lower() not in IMAGE_EXT:
            continue  # this wire format carries images only
        content.append({"type": "image_url", "image_url": {
            "url": f"data:{mime_for(p)};base64,{_b64(p)}"}})

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.15,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    headers.update(extra_headers or {})

    t0 = time.time()
    out, err = _post(f"{base_url.rstrip('/')}/chat/completions", payload, headers, timeout)
    secs = time.time() - t0
    if out is None:
        # Some servers reject response_format; one retry without it.
        if want_json and ("response_format" in err or "HTTP 400" in err):
            payload.pop("response_format", None)
            out, err = _post(f"{base_url.rstrip('/')}/chat/completions",
                             payload, headers, timeout)
            secs = time.time() - t0
        if out is None:
            return {"ok": False, "error": err, "seconds": secs}

    try:
        text = out["choices"][0]["message"]["content"] or ""
    except Exception:
        return {"ok": False, "error": "no choices in response", "seconds": secs}
    u = out.get("usage") or {}
    return {"ok": True, "text": text, "seconds": secs,
            "tokens_in": u.get("prompt_tokens", 0) or 0,
            "tokens_out": u.get("completion_tokens", 0) or 0}


# ---------------------------------------------------------------------------
# Anthropic  (/messages)
# ---------------------------------------------------------------------------
def call_anthropic(model: str, prompt: str, media: list[Path], *,
                   base_url: str, api_key: str, want_json: bool,
                   timeout: int, max_tokens: int = 8192) -> dict:
    content: list[dict] = []
    for p in media:
        if p.suffix.lower() not in IMAGE_EXT:
            continue
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": mime_for(p), "data": _b64(p)}})
    # Anthropic has no JSON mode; asking for bare JSON plus a primed assistant
    # turn is the documented way to get it.
    content.append({"type": "text", "text": prompt})

    messages = [{"role": "user", "content": content}]
    if want_json:
        messages.append({"role": "assistant", "content": [{"type": "text", "text": "{"}]})

    payload = {"model": model, "max_tokens": max_tokens,
               "temperature": 0.15, "messages": messages}
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    t0 = time.time()
    out, err = _post(f"{base_url.rstrip('/')}/messages", payload, headers, timeout)
    secs = time.time() - t0
    if out is None:
        return {"ok": False, "error": err, "seconds": secs}
    try:
        text = "".join(b.get("text", "") for b in out.get("content", []))
    except Exception:
        return {"ok": False, "error": "no content in response", "seconds": secs}
    if want_json:
        text = "{" + text          # put back the primed brace
    u = out.get("usage") or {}
    return {"ok": True, "text": text, "seconds": secs,
            "tokens_in": u.get("input_tokens", 0) or 0,
            "tokens_out": u.get("output_tokens", 0) or 0}


# ---------------------------------------------------------------------------
# Add-a-model: prove it works before saving it
# ---------------------------------------------------------------------------
_PX = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    b"IQAAAABJRU5ErkJggg==")


def test_model(provider: str, model: str, *, api_key: str = "",
               base_url: str = "", timeout: int = 60) -> dict:
    """Fire a real call. Nothing is saved until this passes.

    Also probes vision with a 1x1 PNG, so capabilities are measured rather
    than taken on trust from a checkbox.
    """
    spec = PROVIDER_SPECS.get(provider) or PROVIDER_SPECS["custom"]
    adapter = spec["adapter"]
    base_url = base_url or spec.get("base_url", "")
    api_key = api_key or secrets_store.get_key(spec.get("key_ref") or provider)

    if spec.get("needs_key") and not api_key and adapter != "ollama":
        return {"ok": False, "error": "no API key provided", "caps": []}

    probe = 'Reply with exactly this JSON and nothing else: {"ok": true}'
    caps: list[str] = []

    def _run(with_image: bool) -> dict:
        media: list[Path] = []
        tmp = None
        if with_image:
            tmp = config_tmp()
            tmp.write_bytes(_PX)
            media = [tmp]
        try:
            if adapter == "openai_compatible":
                return call_openai_compatible(
                    model, probe, media, base_url=base_url, api_key=api_key,
                    want_json=True, timeout=timeout)
            if adapter == "anthropic":
                return call_anthropic(
                    model, probe, media, base_url=base_url, api_key=api_key,
                    want_json=True, timeout=timeout, max_tokens=64)
            from . import models as _m
            r = (_m._call_gemini(model, probe, media, grounded=False, thinking=0,
                                 want_json=True, timeout=timeout)
                 if adapter == "gemini" else
                 _m._call_ollama(model, probe, media, want_json=True,
                                 timeout=timeout, cloud=(provider == "ollama_cloud")))
            return {"ok": r.ok, "text": r.text, "seconds": r.seconds,
                    "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                    "error": r.error}
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    base = _run(False)
    if not base.get("ok"):
        return {"ok": False, "error": base.get("error", "call failed"),
                "seconds": base.get("seconds", 0), "caps": []}
    caps.append("json_mode" if "{" in (base.get("text") or "") else "text")

    if "vision" in (spec.get("caps") or []):
        vis = _run(True)
        if vis.get("ok"):
            caps.append("vision")
    if "video" in (spec.get("caps") or []):
        caps.append("video")   # only Gemini declares this today

    return {"ok": True, "seconds": round(base.get("seconds", 0), 2),
            "tokens_in": base.get("tokens_in", 0),
            "tokens_out": base.get("tokens_out", 0),
            "sample": (base.get("text") or "")[:160],
            "caps": caps}


def config_tmp() -> Path:
    from . import config
    d = config.CACHE / "probe"
    d.mkdir(parents=True, exist_ok=True)
    return d / "px.png"


def list_providers() -> list[dict]:
    """What the Add-a-model UI offers, with key status but never the key."""
    out = []
    for name, spec in PROVIDER_SPECS.items():
        ref = spec.get("key_ref") or ""
        key = secrets_store.get_key(ref) if ref else ""
        out.append({
            "name": name, "label": spec["label"], "adapter": spec["adapter"],
            "base_url": spec.get("base_url", ""),
            "needs_key": bool(spec.get("needs_key")),
            "has_key": bool(key), "key_masked": secrets_store.mask(key),
            "signup": spec.get("signup", ""), "caps": spec.get("caps", []),
        })
    return out
