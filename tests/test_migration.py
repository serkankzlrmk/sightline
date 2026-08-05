"""Test the V1 → V2 proposal migration script."""

import sqlite3

import pytest

from config import CHATS_DB_PATH


@pytest.fixture
def temp_v1_proposals():
    """Insert a test V1 proposal into the proposals table and clean V2 artifacts."""
    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.row_factory = sqlite3.Row
    # Clean any previous migration artifacts
    conn.execute("DELETE FROM proposal_v2_setups WHERE id = 'gps_test_migrate_001'")
    now = 1700000000.0
    conn.execute(
        """INSERT OR REPLACE INTO proposals
           (id, uid, title, country, event, themes, donor, date_from, date_to,
            toc, logframe, narrative, created_at, cover_page, background,
            needs_assessment, methodology, budget, mne_framework, risk_matrix,
            sustainability, coordination, current_step, step_status, completed_at,
            pinned_sources, section_sources, beneficiary_data, toc_nodes,
            logframe_data, budget_details, risk_details, mne_plan, review)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "prop_test_migrate_001",
            "test-migrate-uid",
            "Test Migration Proposal",
            "Sudan",
            "Flood Response",
            '["WASH"]',
            "OCHA",
            "",
            "",
            "[]",
            "{}",
            "Test narrative",
            now,
            "{}",
            "Background text",
            "Needs text",
            "Method",
            "{}",
            "{}",
            "[]",
            "Sustain",
            "Coord",
            "cover",
            '{"cover":"approved"}',
            now,
            "[]",
            "{}",
            "{}",
            "[]",
            "{}",
            "{}",
            "[]",
            "[]",
            "",
        ),
    )
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.execute("DELETE FROM proposals WHERE id = 'prop_test_migrate_001'")
    conn.execute("DELETE FROM proposal_v2_setups WHERE id = 'gps_test_migrate_001'")
    conn.commit()
    conn.close()


def test_migrate_dry_run(temp_v1_proposals):
    from scripts.migrate_v1_proposals import migrate

    result = migrate(dry_run=True)
    # Our test proposal should be in the migration count
    assert result["migrated"] >= 1
    assert result["errors"] == 0
    # Verify nothing was actually written — check our specific test proposal wasn't migrated
    conn = sqlite3.connect(str(CHATS_DB_PATH))
    row = conn.execute("SELECT id FROM proposal_v2_setups WHERE id = 'gps_test_migrate_001'").fetchone()
    conn.close()
    assert row is None


def test_migrate_actual(temp_v1_proposals):
    from scripts.migrate_v1_proposals import migrate

    result = migrate(dry_run=False)
    assert result["migrated"] >= 1

    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.row_factory = sqlite3.Row
    v2_row = conn.execute("SELECT * FROM proposal_v2_setups WHERE id = 'gps_test_migrate_001'").fetchone()
    conn.close()

    assert v2_row is not None
    assert v2_row["project_title"] == "Test Migration Proposal"
    assert v2_row["country"] == "Sudan"
    assert v2_row["donor"] == "ocha_cbpf"  # OCHA → ocha_cbpf mapping
    # Step 1 should be locked (completed_at was set)
    assert v2_row["state"] == "locked"


def test_migrate_idempotent(temp_v1_proposals):
    from scripts.migrate_v1_proposals import migrate

    migrate(dry_run=False)
    result2 = migrate(dry_run=False)
    assert result2["migrated"] == 0
    assert result2["skipped"] >= 1
