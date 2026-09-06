from datetime import UTC, datetime

import config
from growth.search_console import get_search_console_dashboard, sync_search_console


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(self.payloads.pop(0))


def test_sync_persists_totals_and_ranked_dimensions(tmp_path, monkeypatch):
    db_path = tmp_path / "growth.db"
    monkeypatch.setattr(config, "GSC_ENABLED", True)
    monkeypatch.setattr(config, "GSC_DB_PATH", db_path)
    monkeypatch.setattr(config, "GSC_SITE_URL", "sc-domain:sightlinehumanitarian.com")
    session = FakeSession(
        [
            {
                "rows": [
                    {"clicks": 12, "impressions": 320, "ctr": 0.0375, "position": 11.4}
                ]
            },
            {
                "rows": [
                    {
                        "keys": ["humanitarian sitrep", "https://sightlinehumanitarian.com/solutions/sitrep"],
                        "clicks": 7,
                        "impressions": 100,
                        "ctr": 0.07,
                        "position": 6.2,
                    },
                    {
                        "keys": ["humanitarian sitrep", "https://sightlinehumanitarian.com/crisis/sudan"],
                        "clicks": 2,
                        "impressions": 80,
                        "ctr": 0.025,
                        "position": 12.1,
                    },
                ]
            },
        ]
    )

    result = sync_search_console(
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
        session=session,
        db_path=db_path,
        lookback_days=28,
        data_lag_days=3,
    )

    assert result["status"] == "completed"
    assert result["start_date"] == "2026-08-07"
    assert result["end_date"] == "2026-09-03"
    assert result["row_count"] == 2
    assert len(session.calls) == 2
    assert session.calls[0]["json"]["aggregationType"] == "byProperty"
    assert session.calls[1]["json"]["dimensions"] == ["query", "page"]
    assert "sc-domain%3Asightlinehumanitarian.com" in session.calls[0]["url"]

    dashboard = get_search_console_dashboard(db_path=db_path)
    assert dashboard["status"] == "ready"
    assert dashboard["snapshot"]["clicks"] == 12
    assert dashboard["top_queries"][0]["value"] == "humanitarian sitrep"
    assert dashboard["top_queries"][0]["clicks"] == 9
    assert dashboard["top_pages"][0]["value"].endswith("/solutions/sitrep")


def test_disabled_sync_makes_no_request(monkeypatch):
    monkeypatch.setattr(config, "GSC_ENABLED", False)
    assert sync_search_console() == {"status": "disabled"}


def test_dashboard_without_snapshot_reports_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GSC_ENABLED", True)
    monkeypatch.setattr(config, "GSC_SITE_URL", "sc-domain:sightlinehumanitarian.com")
    result = get_search_console_dashboard(db_path=tmp_path / "missing.db")
    assert result["status"] == "awaiting_first_sync"
    assert result["snapshot"] is None
