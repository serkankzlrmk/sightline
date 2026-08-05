#!/usr/bin/env python3
"""scripts/migrate_v1_proposals.py

Migrate V1 proposals from the `proposals` table to V2 `proposal_v2_setups`.

V1 donor names (ECHO, USAID, OCHA) are mapped to V2 donor IDs (echo, usaid_bha,
ocha_cbpf).  V1 proposals with only partial content are migrated as draft V2
setups with the appropriate step states.

Idempotent: re-running the script will skip proposals already migrated (matched
by V1 proposal ID kept as the V2 setup ID after stripping the `prop_` prefix).

Usage:
    python scripts/migrate_v1_proposals.py [--dry-run]
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time

# Donor name mapping: V1 label → V2 ID
DONOR_MAP = {
    "echo": "echo",
    "ECHO": "echo",
    "usaid": "usaid_bha",
    "USAID": "usaid_bha",
    "ocha": "ocha_cbpf",
    "OCHA": "ocha_cbpf",
    "cbpf": "ocha_cbpf",
    " europeaid": "europeaid_prag",
    "EuropeAid": "europeaid_prag",
    "PRAG": "europeaid_prag",
    "generic": "generic",
    "Generic": "generic",
}


def _safe_json(val, default):
    if not val:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (TypeError, json.JSONDecodeError):
        return default


def _chats_db_path() -> str:
    import config

    return config.CHATS_DB_PATH


def migrate(dry_run: bool = False) -> dict:
    db_path = _chats_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check if proposals table exists
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "proposals" not in tables:
        print("V1 proposals table does not exist — nothing to migrate.")
        conn.close()
        return {"migrated": 0, "skipped": 0, "errors": 0}

    # Check if proposal_v2_setups exists; create if not
    if "proposal_v2_setups" not in tables:
        print("proposal_v2_setups table does not exist — run the app first to create tables.")
        conn.close()
        return {"migrated": 0, "skipped": 0, "errors": 1}

    # Get existing V2 IDs to skip already-migrated
    existing_v2_ids = {r[0] for r in conn.execute("SELECT id FROM proposal_v2_setups").fetchall()}

    v1_rows = conn.execute("SELECT * FROM proposals ORDER BY created_at ASC").fetchall()
    print(f"Found {len(v1_rows)} V1 proposals, {len(existing_v2_ids)} V2 setups already exist.")

    migrated, skipped, errors = 0, 0, 0

    for row in v1_rows:
        v1_id = row["id"]
        # Create V2 setup ID from V1 ID (strip prop_ prefix, add gps_ prefix)
        v2_id = v1_id if v1_id.startswith("gps_") else f"gps_{v1_id.replace('prop_', '', 1)}"

        if v2_id in existing_v2_ids:
            print(f"  SKIP {v1_id} → {v2_id} (already migrated)")
            skipped += 1
            continue

        try:
            # Map donor
            donor_raw = str(row["donor"] or "").strip()
            donor = DONOR_MAP.get(donor_raw, "generic")

            # Determine step states from V1 step_status
            step_status = _safe_json(row["step_status"], {})
            # Map V1 step_status to V2 step states
            # If V1 proposal has completed_at, treat all steps as locked
            has_completion = row["completed_at"] is not None
            step1_state = "locked" if has_completion or step_status.get("cover") == "approved" else "draft"
            step2_state = "locked" if has_completion or step_status.get("background") == "approved" else "draft"
            step3_state = "locked" if has_completion or step_status.get("logframe") == "approved" else "draft"
            step4_state = "locked" if has_completion else "draft"

            now = row["created_at"] or time.time()

            # Build V2 fields from V1 data
            budget_amount = None
            try:
                budget_data = _safe_json(row["budget"], {})
                if isinstance(budget_data, dict) and budget_data.get("total"):
                    import re

                    nums = re.findall(r"[\d,.]+", str(budget_data["total"]))
                    if nums:
                        budget_amount = float(nums[0].replace(",", ""))
            except Exception:
                pass

            # Step 2 context_data from V1 background + needs_assessment
            context_data = {
                "humanitarian_context": row["background"] or "",
                "needs_assessment": row["needs_assessment"] or "",
                "strategic_justification": "",
                "beneficiaries": {},
            }

            # Step 3 technical_data from V1 toc + logframe
            technical_data = {
                "logframe": _safe_json(row["logframe_data"], {}),
                "toc_narrative": _safe_json(row["toc"], []) or _safe_json(row["toc_nodes"], []),
                "gantt": [],
            }

            # Step 4 financial_data from V1 budget + risk_matrix
            financial_data = {
                "budget_items": [],
                "risks": _safe_json(row["risk_details"], []) or _safe_json(row["risk_matrix"], []),
                "psea_signoff": False,
                "sphere_standards_narrative": "",
            }

            # Build analysis stubs
            step1_analysis = {
                "step_id": 1,
                "is_valid": step1_state == "locked",
                "donor_compliance_score": 75 if step1_state == "locked" else 0,
            }
            step2_analysis = {
                "step_id": 2,
                "is_valid": step2_state == "locked",
                "donor_compliance_score": 75 if step2_state == "locked" else 0,
            }
            step3_analysis = {
                "step_id": 3,
                "is_valid": step3_state == "locked",
                "donor_compliance_score": 75 if step3_state == "locked" else 0,
            }
            step4_analysis = {
                "step_id": 4,
                "is_valid": step4_state == "locked",
                "donor_compliance_score": 75 if step4_state == "locked" else 0,
            }

            if not dry_run:
                conn.execute(
                    """INSERT INTO proposal_v2_setups
                       (id, uid, project_title, country, region, donor, budget_amount,
                        budget_currency, executive_intent, reference_text, reference_filename,
                        sectors, state, analysis, context_data, step2_analysis, step2_state,
                        technical_data, step3_analysis, step3_state,
                        financial_data, step4_analysis, step4_state,
                        locked_at, step2_locked_at, step3_locked_at, step4_locked_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        v2_id,
                        row["uid"] or "migrated",
                        row["title"] or "Migrated Proposal",
                        row["country"] or "",
                        "",
                        donor,
                        budget_amount,
                        "USD",
                        (row["event"] or "")[:500],
                        row["reference_text"] or "",
                        row["reference_filename"] or "",
                        json.dumps(_safe_json(row["themes"], [])),
                        step1_state,
                        json.dumps(step1_analysis),
                        json.dumps(context_data),
                        json.dumps(step2_analysis),
                        step2_state,
                        json.dumps(technical_data),
                        json.dumps(step3_analysis),
                        step3_state,
                        json.dumps(financial_data),
                        json.dumps(step4_analysis),
                        step4_state,
                        row["created_at"] if step1_state == "locked" else None,
                        row["created_at"] if step2_state == "locked" else None,
                        row["created_at"] if step3_state == "locked" else None,
                        row["created_at"] if step4_state == "locked" else None,
                        now,
                        now,
                    ),
                )
                existing_v2_ids.add(v2_id)

            print(
                f"  MIGRATE {v1_id} → {v2_id} (donor={donor}, states={step1_state}/{step2_state}/{step3_state}/{step4_state})"
            )
            migrated += 1

        except Exception as exc:
            print(f"  ERROR {v1_id}: {exc}")
            errors += 1

    if not dry_run:
        conn.commit()
    conn.close()

    summary = {"migrated": migrated, "skipped": skipped, "errors": errors}
    print(f"\nMigration complete: {migrated} migrated, {skipped} skipped, {errors} errors")
    if dry_run:
        print("(dry-run — no changes written)")
    return summary


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    migrate(dry_run=dry)
