"""Job sources: one small module per portal, found by the registry (docs/ADDING-A-SOURCE.md).

A source module defines
  NAME, COUNTRY ("AU", ... or "*" for any), DESCRIPTION, KEYS (the search keys it reads), NEEDS_LOGIN = False
  search(search: dict, max_age_days: int) -> list[dict]      items, or [{"_error": "..."}]
  detail(job_id: str) -> str                                 optional: full ad text, already guarded
  alive(job_id: str) -> (bool | None, closes | None)         optional: still open? None = could not tell
  route(job_id: str) -> ("quick" | "external", ats) | None   optional: how the job is applied for (on the portal, or on the
                                                              employer's site and in which system); None = could not tell
  APPLY = ("external", "greenhouse")                         optional: the same, fixed, for a feed whose postings are the form
  configured() -> bool                                       optional: False while a key/setting is missing
  SETUP = "..."                                               optional: how to configure it (shown by `job doctor`)
  DETAIL_DELAY = (lo, hi)                                    optional: seconds to wait after each detail() call
Dropping a module into this folder is enough: nothing else lists it.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

REQUIRED = ("NAME", "COUNTRY", "DESCRIPTION", "NEEDS_LOGIN", "search")
REGISTRY: dict[str, ModuleType] = {}


def problems(mod: ModuleType) -> list[str]:
    """What a source module is missing or breaks (empty = valid)."""
    out = [f"missing {a}" for a in REQUIRED if not hasattr(mod, a)]
    if getattr(mod, "NEEDS_LOGIN", False):
        out.append("NEEDS_LOGIN must be False: the harness never logs in to read ads")
    return out


def _load() -> None:
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda x: x.name):
        if m.name.startswith("_") or m.name == "base":
            continue
        mod = importlib.import_module(f"{__name__}.{m.name}")
        bad = problems(mod)
        if bad:
            raise ImportError(f"source '{m.name}': {', '.join(bad)}")
        REGISTRY[mod.NAME] = mod


def get(name: str) -> ModuleType | None:
    return REGISTRY.get(name)


def names() -> list[str]:
    return list(REGISTRY)


def has(name: str, fn: str) -> bool:
    """Does this source offer the optional function (detail, alive)?"""
    return callable(getattr(REGISTRY.get(name), fn, None))


def configured(mod: ModuleType) -> bool:
    return bool(getattr(mod, "configured", lambda: True)())


def info() -> list[dict]:
    """One row per source, for `job doctor`."""
    return [{"name": m.NAME, "country": m.COUNTRY, "description": m.DESCRIPTION, "keys": getattr(m, "KEYS", ""),
             "needs_login": m.NEEDS_LOGIN, "configured": configured(m),
             "setup": getattr(m, "SETUP", ""),
             "detail": has(n, "detail"), "alive": has(n, "alive")} for n, m in REGISTRY.items()]


_load()
