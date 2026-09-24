"""What models exist, which are on, and what order they run in.

config.py is only the seed. Once the UI touches anything it writes
data/models.json and that wins, so changing models isn't a code edit.
A ladder is just an ordered list, first one is primary.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import config, providers, secrets_store

STORE = config.DATA / "models.json"

# Measured on 2026-09-23; see config.py for the head-to-head that produced it.
_SEED_FREE = config.FREE_TIER_RPD


def _seed() -> dict:
    """Build the initial registry from the hard-coded ladders."""
    models: dict[str, dict] = {}
    for task, rungs in config.LADDERS.items():
        for provider, model in rungs:
            mid = f"{provider}/{model}"
            if mid in models:
                continue
            spec = providers.PROVIDER_SPECS.get(provider, {})
            models[mid] = {
                "id": mid, "provider": provider, "model": model,
                "label": model, "enabled": True,
                "caps": list(spec.get("caps") or []),
                "free_rpd": _SEED_FREE.get(model, 0),
                "added_at": time.time(), "verified_at": 0, "notes": "",
            }
    ladders = {t: [f"{p}/{m}" for p, m in rungs] for t, rungs in config.LADDERS.items()}
    return {"version": 1, "models": models, "ladders": ladders,
            "thinking": dict(config.THINKING_BUDGET)}


def load() -> dict:
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
        if d.get("models"):
            return d
    except Exception:
        pass
    d = _seed()
    save(d)
    return d


def save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Reads used by the router
# ---------------------------------------------------------------------------
def ladder_for(task: str) -> list[tuple[str, str]]:
    """Ordered (provider, model) rungs for a task, enabled ones only."""
    d = load()
    ids = d["ladders"].get(task) or d["ladders"].get("classify") or []
    out: list[tuple[str, str]] = []
    for mid in ids:
        m = d["models"].get(mid)
        if not m or not m.get("enabled", True):
            continue
        out.append((m["provider"], m["model"]))
    return out


def caps_for(provider: str, model: str) -> list[str]:
    d = load()
    m = d["models"].get(f"{provider}/{model}")
    if m and m.get("caps"):
        return list(m["caps"])
    return list((providers.PROVIDER_SPECS.get(provider) or {}).get("caps") or [])


def free_rpd() -> dict[str, int]:
    d = load()
    return {m["model"]: int(m.get("free_rpd") or 0)
            for m in d["models"].values() if m.get("free_rpd")}


def thinking_for(task: str) -> int:
    return int((load().get("thinking") or {}).get(task, 0))


# ---------------------------------------------------------------------------
# Writes used by the UI
# ---------------------------------------------------------------------------
def add_model(provider: str, model: str, *, label: str = "", caps: list | None = None,
              free_rpd_: int = 0, verified: bool = False) -> dict:
    d = load()
    mid = f"{provider}/{model}"
    spec = providers.PROVIDER_SPECS.get(provider, {})
    d["models"][mid] = {
        "id": mid, "provider": provider, "model": model,
        "label": label or model, "enabled": True,
        "caps": caps if caps is not None else list(spec.get("caps") or []),
        "free_rpd": free_rpd_,
        "added_at": time.time(),
        "verified_at": time.time() if verified else 0,
        "notes": "",
    }
    save(d)
    return d["models"][mid]


def remove_model(mid: str) -> None:
    d = load()
    d["models"].pop(mid, None)
    for task in d["ladders"]:
        d["ladders"][task] = [x for x in d["ladders"][task] if x != mid]
    save(d)


def set_enabled(mid: str, enabled: bool) -> None:
    d = load()
    if mid in d["models"]:
        d["models"][mid]["enabled"] = bool(enabled)
        save(d)


def set_ladder(task: str, ids: list[str]) -> None:
    """Replace a task's ladder. Order IS the priority."""
    d = load()
    d["ladders"][task] = [i for i in ids if i in d["models"]]
    save(d)


def set_thinking(task: str, budget: int) -> None:
    d = load()
    d.setdefault("thinking", {})[task] = max(0, int(budget))
    save(d)


# ---------------------------------------------------------------------------
# What the UI renders
# ---------------------------------------------------------------------------
def overview() -> dict:
    from . import models as _m

    d = load()
    quota = _m.quota_snapshot()
    used = {m["model"]: m["used"] for m in quota.get("models", [])}

    rows = []
    for mid, m in sorted(d["models"].items()):
        spec = providers.PROVIDER_SPECS.get(m["provider"], {})
        ref = spec.get("key_ref") or ""
        rows.append({
            **m,
            "provider_label": spec.get("label", m["provider"]),
            "needs_key": bool(spec.get("needs_key")),
            "has_key": bool(secrets_store.get_key(ref)) if ref else True,
            "used_today": used.get(m["model"], 0),
            "in_ladders": [t for t, ids in d["ladders"].items() if mid in ids],
        })

    return {
        "models": rows,
        "ladders": d["ladders"],
        "thinking": d.get("thinking", {}),
        "tasks": list(d["ladders"].keys()),
        "providers": providers.list_providers(),
        "secrets": secrets_store.status(),
    }
