"""
proposal_bridge.py — embeds Proposal Studio blueprints into the Sightline app.

Sightline's server.py calls this module. The Proposal repo lives at
/app/proposal (volume mount) in production; imports resolve from there.
Set PROPOSAL_BRIDGE=0 to disable for local development.

Module-name isolation:
  Proposal blueprints use `from config import ...` / `from db import ...`
  which COLLIDES with Sightline's own `config` module. Solution: add the
  Proposal root to sys.path; blueprint modules were rewritten to resolve
  `from proposal.config import ...` / `from proposal.db import ...` first
  (embedded), falling back to plain names (standalone) — see
  proposal/blueprints/*.py.
"""

import os
import sys

_PROPOSAL_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proposal")


def register_proposal_blueprints(app) -> bool:
    if os.getenv("PROPOSAL_BRIDGE", "1") == "0":
        app.logger.info("proposal_bridge: disabled via PROPOSAL_BRIDGE=0")
        return False
    if not os.path.isdir(_PROPOSAL_ROOT):
        app.logger.warning("proposal_bridge: %s not found — Proposal Studio unavailable", _PROPOSAL_ROOT)
        return False
    # Add the PARENT of the Proposal root to sys.path so `proposal` resolves
    # as a namespace package (proposal/db.py, proposal/engine/...). Blueprints
    # use `from proposal.db import ...` (embedded); plain names as fallback.
    _parent = os.path.dirname(_PROPOSAL_ROOT)
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    # Fallback: also add the root itself (legacy plain-import pattern)
    if _PROPOSAL_ROOT not in sys.path:
        sys.path.insert(0, _PROPOSAL_ROOT)
    # ── Auth unification ─────────────────────────────────────────────────
    # `auth` exists in both repos with the same API. Preload Sightline's auth
    # into sys.modules so blueprint `from auth import ...` statements resolve
    # to Sightline's auth (single source, single role logic).
    try:
        import auth as _sightline_auth
        if "current_uid" in dir(_sightline_auth) and "require_auth" in dir(_sightline_auth):
            sys.modules.setdefault("auth", _sightline_auth)
    except Exception as _auth_exc:  # pragma: no cover
        app.logger.warning("proposal_bridge: auth preload failed (%s) — falling back to Proposal auth", _auth_exc)
    try:
        from proposal.blueprints.proposal_api import proposal_api_bp
        from proposal.blueprints.step3_logframe import step3_api_bp
        from proposal.blueprints.step4_budget_risk import step4_api_bp
        from proposal.blueprints.call_ingest_api import call_ingest_bp
    except Exception as exc:  # pragma: no cover
        app.logger.warning("proposal_bridge: blueprint import failed: %s", exc)
        return False
    app.register_blueprint(proposal_api_bp)
    app.register_blueprint(step3_api_bp)
    app.register_blueprint(step4_api_bp)
    app.register_blueprint(call_ingest_bp)
    app.logger.info(
        "proposal_bridge: Proposal Studio blueprints registered from %s",
        _PROPOSAL_ROOT,
    )
    return True


def proposal_root() -> str:
    """Proposal repo root (used for static/template serving)."""
    return _PROPOSAL_ROOT


def proposal_asset_version() -> str:
    """Return a deploy-stable cache key for Proposal Studio frontend assets."""
    candidates = (
        os.path.join(_PROPOSAL_ROOT, "static", "js", "app.js"),
        os.path.join(_PROPOSAL_ROOT, "static", "js", "proposal-auth.js"),
        os.path.join(_PROPOSAL_ROOT, "static", "css", "proposal.css"),
    )
    mtimes = [os.stat(path).st_mtime_ns for path in candidates if os.path.exists(path)]
    return format(max(mtimes, default=0), "x")
