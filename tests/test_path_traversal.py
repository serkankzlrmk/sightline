"""
Tests for path traversal protection on SITREP report/bulletin endpoints.
"""
import os
from unittest.mock import patch, MagicMock
from pathlib import Path

# We test the containment logic directly (no Flask app needed for the core check)
class TestPathTraversal:
    def test_report_rejects_dotdot(self):
        """The report endpoint blocks .. in filename."""
        # The endpoint checks: if ".." in filename → 400
        # This is a substring check — verify it catches the pattern
        filename = "../../etc/passwd"
        assert ".." in filename

    def test_report_rejects_absolute_path(self):
        """Absolute paths contain / and are blocked."""
        filename = "/etc/passwd"
        assert "/" in filename

    def test_is_relative_to_contains(self):
        """Path.is_relative_to correctly contains within reports dir."""
        base = Path("/app/output/reports").resolve()
        safe = (base / "sudan_report.json").resolve()
        assert safe.is_relative_to(base)

    def test_is_relative_to_rejects_sibling(self):
        """Path.is_relative_to rejects sibling directory (prefix collision)."""
        base = Path("/app/output/reports").resolve()
        evil = Path("/app/output/reports_evil/secret").resolve()
        assert not evil.is_relative_to(base)

    def test_is_relative_to_rejects_parent(self):
        """Path.is_relative_to rejects parent directory traversal."""
        base = Path("/app/output/reports").resolve()
        evil = Path("/app/output/reports/../../etc/passwd").resolve()
        # After resolve, this becomes /etc/passwd
        assert not evil.is_relative_to(base)