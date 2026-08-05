import json
from unittest.mock import patch

import pytest

import auth
import blueprints.guided_proposal as guided_proposal
import server
from config import CHATS_DB_PATH

VALID_SETUP = {
    "project_title": "Inclusive WASH Response for Flood-Affected Families",
    "country": "Sudan",
    "region": "Khartoum",
    "donor": "ocha_cbpf",
    "budget_amount": 250000,
    "budget_currency": "USD",
    "executive_intent": "This humanitarian intervention will target flood-affected families with safe water, hygiene supplies, and community-led protection support, with explicit attention to women, children, older people, and persons with disabilities.",
    "sectors": ["WASH", "Protection"],
}

VALID_STEP2 = {
    "humanitarian_context": "Flooding and displacement caused by crisis and conflict have disrupted essential services across Khartoum. The response follows humanity, neutrality, impartiality, and operational independence.",
    "needs_assessment": "Women, girls, boys, older people, and persons with disabilities face acute WASH and protection needs. Gender and disability inclusion shape outreach, while GBV referral pathways are available.",
    "strategic_justification": "Our local partner network has sustained operational presence and technical WASH expertise with added value and capacity in the target area.",
    "beneficiaries": {
        "host_communities": {
            "men_18_59": 10,
            "women_18_59": 10,
            "boys_0_17": 10,
            "girls_0_17": 10,
            "elderly_60_plus": 5,
            "persons_with_disabilities": 5,
        },
        "idps": {
            "men_18_59": 40,
            "women_18_59": 40,
            "boys_0_17": 40,
            "girls_0_17": 40,
            "elderly_60_plus": 20,
            "persons_with_disabilities": 20,
        },
        "refugees_returnees": {
            "men_18_59": 20,
            "women_18_59": 20,
            "boys_0_17": 20,
            "girls_0_17": 20,
            "elderly_60_plus": 10,
            "persons_with_disabilities": 10,
        },
    },
}

VALID_STEP3 = {
    "grant_months": 12,
    "toc_narrative": "When planned activities are delivered with communities, they create measurable outputs that contribute to outcomes and, over time, the intended impact.",
    "hypotheses": ["Access remains possible.", "Local partners can safely deliver assistance."],
    "logframe": [
        {
            "id": "impact-1",
            "level": "impact",
            "parent_id": "",
            "intervention_logic": "Crisis-affected people have improved wellbeing.",
            "means_of_verification": "Annual assessment",
            "assumptions": "Conditions stabilize.",
        },
        {
            "id": "outcome-1",
            "level": "outcome",
            "parent_id": "impact-1",
            "intervention_logic": "Target households access safe services.",
            "means_of_verification": "Household survey",
            "assumptions": "Services remain accessible.",
            "indicators": [
                {
                    "indicator_title": "Households accessing safe water",
                    "indicator_type": "Standard",
                    "baseline_value": "0",
                    "target_value": "500",
                    "unit_of_measure": "Number",
                    "disaggregation": "Age, gender, disability",
                    "data_source_and_frequency": "Kobo survey / quarterly",
                }
            ],
        },
        {
            "id": "output-1",
            "level": "output",
            "parent_id": "outcome-1",
            "intervention_logic": "Water points are rehabilitated.",
            "means_of_verification": "Completion reports",
            "assumptions": "Supplies are available.",
            "indicators": [
                {
                    "indicator_title": "Water points rehabilitated",
                    "indicator_type": "Standard",
                    "baseline_value": "0",
                    "target_value": "10",
                    "unit_of_measure": "Number",
                    "disaggregation": "Location",
                    "data_source_and_frequency": "Site verification / monthly",
                }
            ],
        },
        {
            "id": "activity-1",
            "level": "activity",
            "parent_id": "output-1",
            "intervention_logic": "Rehabilitate water points.",
            "means_of_verification": "Work plans",
            "assumptions": "Contractors can access sites.",
        },
    ],
    "gantt": [{"activity_id": "activity-1", "months": [1, 2, 3]}],
}


@pytest.fixture(autouse=True)
def guided_proposal_enabled():
    # V2 is now always enabled — no patch needed.
    yield


@pytest.fixture
def client():
    return server.app.test_client()


@pytest.fixture(autouse=True)
def clean_setups():
    import sqlite3

    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.execute("DELETE FROM proposal_v2_setups WHERE uid LIKE 'test-v2-%'")
    conn.commit()
    conn.close()
    yield


def _headers():
    return {"Authorization": "Bearer token"}


def _premium_auth():
    return patch.object(auth, "verify_firebase_token", return_value={"uid": "test-v2-user", "role": "premium"})


def test_setup_requires_auth(client):
    with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
        response = client.post("/api/proposals/setups", json=VALID_SETUP)
    assert response.status_code == 401


def test_draft_analyze_and_lock_flow(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        assert created.status_code == 201
        setup = json.loads(created.data)
        assert setup["state"] == "draft"

        with patch(
            "agent.proposal_v2_agents.analyze_step_one",
            return_value={
                "step_id": 1,
                "is_valid": True,
                "donor_compliance_score": 92,
                "critique_notes": [],
                "suggested_improvements": [],
                "analyzed_at": 1,
            },
        ):
            analysis = client.post(f"/api/proposals/setups/{setup['id']}/analyze", headers=_headers())
        analysis_data = json.loads(analysis.data)
        assert analysis.status_code == 200
        assert analysis_data["is_valid"] is True
        assert analysis_data["donor_compliance_score"] == 92

        locked = client.post(f"/api/proposals/setups/{setup['id']}/lock", headers=_headers())
        locked_data = json.loads(locked.data)
        assert locked.status_code == 200
        assert locked_data["state"] == "locked"
        assert locked_data["locked_at"] is not None

        update = client.put(f"/api/proposals/setups/{setup['id']}", headers=_headers(), json=VALID_SETUP)
        assert update.status_code == 409


def test_step1_ai_draft_returns_editable_fields(client):
    """Co-writing is separate from compliance analysis and stays editable."""
    ai_draft = {
        "project_title": "Inclusive WASH Support for Flood-Affected Families",
        "country": "Sudan",
        "region": "Khartoum",
        "donor": "ocha_cbpf",
        "budget_amount": 250000,
        "budget_currency": "USD",
        "executive_intent": "The project will provide safe water, hygiene supplies, and inclusive protection support for flood-affected families in Khartoum, prioritising women, children, older people, and persons with disabilities.",
        "sectors": ["WASH", "Protection"],
        "draft_notes": ["Review the target locations before analysis."],
    }
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        setup_id = json.loads(created.data)["id"]
        with patch("agent.proposal_v2_agents.generate_step_one_draft", return_value=ai_draft):
            response = client.post(f"/api/proposals/setups/{setup_id}/generate-draft", headers=_headers())

    data = json.loads(response.data)
    assert response.status_code == 200
    assert data["draft"] == ai_draft
    assert data["generated_at"] > 0


def test_call_brief_explains_uploaded_reference_without_changing_setup(client):
    brief = {
        "overview": "The call funds community protection work.",
        "eligible_applicants": ["Registered NGOs"],
        "priority_outcomes": ["Prevent CEFM"],
        "required_deliverables": ["Narrative and budget"],
        "financial_and_timing": ["Deadline: 1 April"],
        "evaluation_criteria": ["Technical quality"],
        "open_questions": ["Budget ceiling is not specified."],
        "important_notes": ["Use the provided template."],
    }
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        setup_id = json.loads(created.data)["id"]
        with patch("agent.proposal_v2_agents.summarize_call_document", return_value=brief):
            with patch.object(
                guided_proposal,
                "_serialize",
                return_value={**VALID_SETUP, "reference_text": "Call text", "reference_filename": "call.docx"},
            ):
                response = client.post(f"/api/proposals/setups/{setup_id}/call-brief", headers=_headers())

    data = json.loads(response.data)
    assert response.status_code == 200
    assert data["brief"] == brief
    assert data["filename"] == "call.docx"


def test_step2_can_generate_a_first_draft_without_user_narratives(client):
    generated = {
        "humanitarian_context": "Flooding disrupted essential services.",
        "needs_assessment": "Women and children need safe water and protection support.",
        "strategic_justification": "The intervention builds on local delivery capacity.",
        "draft_notes": ["Confirm beneficiary totals."],
        "sources": [],
    }
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        setup_id = json.loads(created.data)["id"]
        with patch(
            "agent.proposal_v2_agents.analyze_step_one", return_value={"is_valid": True, "donor_compliance_score": 92}
        ):
            client.post(f"/api/proposals/setups/{setup_id}/analyze", headers=_headers())
        client.post(f"/api/proposals/setups/{setup_id}/lock", headers=_headers())
        with patch("agent.proposal_v2_agents.generate_step_two_draft", return_value=generated):
            response = client.post(f"/api/proposals/setups/{setup_id}/generate-step2-draft", headers=_headers())

    assert response.status_code == 200
    assert json.loads(response.data)["draft"] == generated


def test_invalid_setup_cannot_be_locked(client):
    invalid = {**VALID_SETUP, "project_title": "Short", "budget_amount": 0}
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=invalid)
        setup_id = json.loads(created.data)["id"]
        response = client.post(f"/api/proposals/setups/{setup_id}/lock", headers=_headers())
        data = json.loads(response.data)
        assert response.status_code == 422
        assert data["analysis"]["is_valid"] is False
        assert {v["field"] for v in data["analysis"]["violations"]} >= {"project_title", "budget_amount"}


def test_guided_setup_can_be_deleted_by_its_owner(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        setup_id = json.loads(created.data)["id"]

        deleted = client.delete(f"/api/proposals/setups/{setup_id}", headers=_headers())
        assert deleted.status_code == 200
        assert json.loads(deleted.data)["message"] == "Guided proposal deleted."

        missing = client.get(f"/api/proposals/setups/{setup_id}", headers=_headers())
        assert missing.status_code == 404


def test_guided_setup_list_exposes_server_authoritative_delete_capability(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        listed = client.get("/api/proposals/setups", headers=_headers())
        assert listed.status_code == 200
        assert json.loads(listed.data)[0]["can_delete"] is True


def test_step2_requires_locked_step1_and_locks_immutable_context(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        created = client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP)
        setup = json.loads(created.data)
        blocked = client.post(
            "/api/proposals/steps/2/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2}
        )
        assert blocked.status_code == 409

        with patch(
            "agent.proposal_v2_agents.analyze_step_one",
            return_value={
                "step_id": 1,
                "is_valid": True,
                "donor_compliance_score": 92,
                "critique_notes": [],
                "suggested_improvements": [],
                "analyzed_at": 1,
            },
        ):
            client.post(f"/api/proposals/setups/{setup['id']}/analyze", headers=_headers())
        assert client.post(f"/api/proposals/setups/{setup['id']}/lock", headers=_headers()).status_code == 200

        verifier = {
            "step_id": 2,
            "is_valid": True,
            "donor_compliance_score": 88,
            "critique_notes": ["Context is coherent."],
            "suggested_improvements": [],
            "analyzed_at": 1,
        }
        with patch("agent.proposal_v2_agents.analyze_step_two", return_value=verifier):
            analyzed = client.post(
                "/api/proposals/steps/2/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2}
            )
        data = json.loads(analyzed.data)
        assert analyzed.status_code == 200
        assert data["beneficiary_summary"]["total_beneficiaries"] == 350
        assert data["sections_metrics"]["needs_assessment"]["max_allowed"] == 4000

        locked = client.post(
            "/api/proposals/steps/2/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2}
        )
        locked_data = json.loads(locked.data)
        assert locked.status_code == 200
        assert locked_data["step2_state"] == "locked"
        assert locked_data["step2_locked_at"] is not None


def test_step2_analysis_never_allows_llm_to_override_structural_validation(client):
    """A positive verifier score cannot turn an incomplete context into a lockable step."""
    incomplete = {**VALID_STEP2, "humanitarian_context": ""}
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        with patch(
            "agent.proposal_v2_agents.analyze_step_one", return_value={"is_valid": True, "donor_compliance_score": 92}
        ):
            client.post(f"/api/proposals/setups/{setup['id']}/analyze", headers=_headers())
        client.post(f"/api/proposals/setups/{setup['id']}/lock", headers=_headers())

        with patch(
            "agent.proposal_v2_agents.analyze_step_two", return_value={"is_valid": True, "donor_compliance_score": 100}
        ):
            analyzed = client.post(
                "/api/proposals/steps/2/analyze", headers=_headers(), json={"setup_id": setup["id"], **incomplete}
            )

    data = json.loads(analyzed.data)
    assert analyzed.status_code == 200
    assert data["donor_compliance_score"] == 100
    assert data["is_valid"] is False
    assert any(item["field"] == "humanitarian_context" for item in data["violations"])


def test_step3_requires_a_traceable_parent_for_each_non_impact_row(client):
    malformed = {
        **VALID_STEP3,
        "logframe": [{**row, "parent_id": ""} if row["level"] == "output" else row for row in VALID_STEP3["logframe"]],
    }
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        with patch(
            "agent.proposal_v2_agents.analyze_step_one", return_value={"is_valid": True, "donor_compliance_score": 92}
        ):
            client.post(f"/api/proposals/setups/{setup['id']}/analyze", headers=_headers())
        client.post(f"/api/proposals/setups/{setup['id']}/lock", headers=_headers())
        with patch(
            "agent.proposal_v2_agents.analyze_step_two", return_value={"is_valid": True, "donor_compliance_score": 90}
        ):
            client.post(
                "/api/proposals/steps/2/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2}
            )
        client.post("/api/proposals/steps/2/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2})
        with patch(
            "agent.proposal_v2_agents.analyze_step_three",
            return_value={"is_valid": True, "donor_compliance_score": 100},
        ):
            analyzed = client.post(
                "/api/proposals/steps/3/analyze", headers=_headers(), json={"setup_id": setup["id"], **malformed}
            )

    data = json.loads(analyzed.data)
    assert analyzed.status_code == 200
    assert data["is_valid"] is False
    assert any(item["field"] == "logframe_relationship" for item in data["violations"])


def test_step3_requires_locked_step2_then_analyzes_and_locks(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        blocked = client.post(
            "/api/proposals/steps/3/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP3}
        )
        assert blocked.status_code == 409

        with patch(
            "agent.proposal_v2_agents.analyze_step_one", return_value={"is_valid": True, "donor_compliance_score": 92}
        ):
            client.post(f"/api/proposals/setups/{setup['id']}/analyze", headers=_headers())
        client.post(f"/api/proposals/setups/{setup['id']}/lock", headers=_headers())
        with patch(
            "agent.proposal_v2_agents.analyze_step_two", return_value={"is_valid": True, "donor_compliance_score": 88}
        ):
            client.post(
                "/api/proposals/steps/2/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2}
            )
        client.post("/api/proposals/steps/2/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP2})

        verifier = {
            "step_id": 3,
            "is_valid": True,
            "donor_compliance_score": 90,
            "critique_notes": ["Vertical logic is coherent."],
            "suggested_improvements": [],
        }
        with patch("agent.proposal_v2_agents.analyze_step_three", return_value=verifier):
            analyzed = client.post(
                "/api/proposals/steps/3/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP3}
            )
        data = json.loads(analyzed.data)
        assert analyzed.status_code == 200
        assert data["logframe_metrics"] == {
            "outcomes_count": 1,
            "outputs_count": 1,
            "activities_count": 1,
            "indicators_smart_rate": 100.0,
        }

        locked = client.post(
            "/api/proposals/steps/3/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP3}
        )
        assert locked.status_code == 200
        assert json.loads(locked.data)["step3_state"] == "locked"


VALID_STEP4 = {
    "budget_items": [
        {
            "item_code": "STF-01",
            "category": 1,
            "description": "Project coordinator",
            "unit_type": "month",
            "quantity": 12,
            "unit_cost": 3000,
            "duration_frequency": 1,
            "donor_grant_share": 36000,
            "co_financing_share": 0,
        },
        {
            "item_code": "SUP-01",
            "category": 2,
            "description": "Hygiene kits",
            "unit_type": "kit",
            "quantity": 500,
            "unit_cost": 25,
            "duration_frequency": 1,
            "donor_grant_share": 12500,
            "co_financing_share": 0,
        },
        {
            "item_code": "OVR-01",
            "category": 5,
            "description": "Indirect costs (7%)",
            "unit_type": "lump",
            "quantity": 1,
            "unit_cost": 2500,
            "duration_frequency": 1,
            "donor_grant_share": 2500,
            "co_financing_share": 0,
        },
    ],
    "risks": [
        {
            "category": "Security",
            "risk_description": "Access constraints due to conflict",
            "likelihood": 3,
            "impact": 4,
            "mitigation_strategy": "Remote monitoring and local partner coordination.",
        },
    ],
    "psea_signoff": True,
    "sphere_standards_narrative": "The project adheres to Sphere standards for WASH interventions, ensuring minimum standards in disaster response.",
}


def _lock_steps_1_through_3(client, setup_id):
    """Helper: lock Steps 1-3 so Step 4 / Step 5 tests can proceed."""
    with patch(
        "agent.proposal_v2_agents.analyze_step_one", return_value={"is_valid": True, "donor_compliance_score": 92}
    ):
        client.post(f"/api/proposals/setups/{setup_id}/analyze", headers=_headers())
    client.post(f"/api/proposals/setups/{setup_id}/lock", headers=_headers())
    with patch(
        "agent.proposal_v2_agents.analyze_step_two", return_value={"is_valid": True, "donor_compliance_score": 88}
    ):
        client.post("/api/proposals/steps/2/analyze", headers=_headers(), json={"setup_id": setup_id, **VALID_STEP2})
    client.post("/api/proposals/steps/2/lock", headers=_headers(), json={"setup_id": setup_id, **VALID_STEP2})
    with patch(
        "agent.proposal_v2_agents.analyze_step_three", return_value={"is_valid": True, "donor_compliance_score": 90}
    ):
        client.post("/api/proposals/steps/3/analyze", headers=_headers(), json={"setup_id": setup_id, **VALID_STEP3})
    client.post("/api/proposals/steps/3/lock", headers=_headers(), json={"setup_id": setup_id, **VALID_STEP3})


def test_step4_requires_locked_step3_then_analyzes_and_locks(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        _lock_steps_1_through_3(client, setup["id"])

        analyzed = client.post(
            "/api/proposals/steps/4/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP4}
        )
        data = json.loads(analyzed.data)
        assert analyzed.status_code == 200
        assert data["is_valid"] is True
        assert data["financial_summary"]["total_budget"] > 0
        assert data["financial_summary"]["indirect_overhead_percentage"] <= 7  # OCHA cap

        locked = client.post(
            "/api/proposals/steps/4/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP4}
        )
        assert locked.status_code == 200
        locked_data = json.loads(locked.data)
        assert locked_data["step4_state"] == "locked"
        assert locked_data["step4_locked_at"] is not None


def test_step5_summary_and_evaluate_require_all_locked(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        _lock_steps_1_through_3(client, setup["id"])
        client.post("/api/proposals/steps/4/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP4})
        client.post("/api/proposals/steps/4/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP4})

        summary = client.get(f"/api/proposals/setups/{setup['id']}/summary", headers=_headers())
        assert summary.status_code == 200
        summary_data = json.loads(summary.data)
        assert summary_data["completion"] == "locked"

        evaluate = client.post(f"/api/proposals/setups/{setup['id']}/evaluate", headers=_headers())
        assert evaluate.status_code == 200
        eval_data = json.loads(evaluate.data)
        assert "overall_score" in eval_data
        assert "prag_status" in eval_data
        assert eval_data["prag_status"] in ("APPROVED_FOR_SUBMISSION", "AUTOMATIC_REJECTION")


def test_step5_compile_pdf_requires_all_locked(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        _lock_steps_1_through_3(client, setup["id"])
        client.post("/api/proposals/steps/4/analyze", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP4})
        client.post("/api/proposals/steps/4/lock", headers=_headers(), json={"setup_id": setup["id"], **VALID_STEP4})

        pdf_response = client.post(f"/api/proposals/setups/{setup['id']}/compile-pdf", headers=_headers())
        assert pdf_response.status_code == 200
        assert pdf_response.mimetype == "application/pdf"
        assert len(pdf_response.data) > 1000  # PDF should be non-trivial


def test_summary_blocked_before_all_locked(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        setup = json.loads(client.post("/api/proposals/setups", headers=_headers(), json=VALID_SETUP).data)
        # Only Step 1 locked, Steps 2-4 are draft
        with patch(
            "agent.proposal_v2_agents.analyze_step_one", return_value={"is_valid": True, "donor_compliance_score": 92}
        ):
            client.post(f"/api/proposals/setups/{setup['id']}/analyze", headers=_headers())
        client.post(f"/api/proposals/setups/{setup['id']}/lock", headers=_headers())

        summary = client.get(f"/api/proposals/setups/{setup['id']}/summary", headers=_headers())
        assert summary.status_code == 409


def test_donor_list_includes_supported_donors(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        response = client.get("/api/proposals/donors", headers=_headers())
        assert response.status_code == 200
        donors = json.loads(response.data)
        donor_ids = {d["id"] for d in donors}
    assert donor_ids == {"ocha_cbpf", "usaid_bha", "europeaid_prag", "echo", "unfpa", "generic"}


# ── Manifest-driven donor rules tests ────────────────────────────────────────


def test_donor_rules_endpoint_returns_manifest(client):
    with patch.object(auth, "_dev_mode", return_value=False), _premium_auth():
        response = client.get("/api/proposals/donor-rules", headers=_headers())
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "version" in data
        assert "donors" in data
        assert len(data["donors"]) == 6
        ocha = next(d for d in data["donors"] if d["id"] == "ocha_cbpf")
        assert ocha["overhead_ceiling_percent"] == 7.0
        assert ocha["max_duration_months"] == 12
        assert "step1_executive_intent" in ocha["section_rules"]
        assert "humanitarian" in ocha["section_rules"]["step1_executive_intent"]["mandatory_tokens"]


def test_ocha_cbpf_step1_mandatory_tokens_enforced():
    """OCHA Step 1 requires 'humanitarian' and 'target' in executive intent."""
    from agent.proposal_v2_rules import normalize_setup, validate_setup

    setup = normalize_setup(
        {
            "project_title": "WASH Response for Flood Victims",
            "country": "Sudan",
            "donor": "ocha_cbpf",
            "budget_amount": 100000,
            "budget_currency": "USD",
            "executive_intent": "This project provides water and sanitation to affected communities without using the required keywords.",
            "sectors": ["WASH"],
        }
    )
    result = validate_setup(setup)
    assert not result["is_valid"]
    token_violations = [v for v in result["violations"] if "concepts" in v["message"]]
    assert len(token_violations) > 0


def test_generic_donor_has_relaxed_rules():
    """Generic donor: min 50 chars intent, no mandatory tokens, sphere optional, max 5 outcomes."""
    from agent.proposal_v2_rules import normalize_setup, normalize_step4, validate_setup, validate_step4

    setup = normalize_setup(
        {
            "project_title": "Generic Relief Project",
            "country": "Somalia",
            "donor": "generic",
            "budget_amount": 50000,
            "budget_currency": "USD",
            "executive_intent": "Short intent that is over fifty characters long for testing generic donor rules here.",
            "sectors": ["Protection"],
        }
    )
    result = validate_setup(setup)
    assert result["is_valid"], f"Generic should pass with 50+ char intent: {result['violations']}"

    # Generic: sphere_standards_required=False, PSEA still required
    step4 = normalize_step4(
        {
            "budget_items": [
                {
                    "category": 1,
                    "description": "Staff",
                    "unit_type": "month",
                    "quantity": 1,
                    "unit_cost": 1000,
                    "duration_frequency": 1,
                    "donor_grant_share": 1000,
                    "co_financing_share": 0,
                }
            ],
            "risks": [
                {
                    "category": "Security",
                    "risk_description": "Test",
                    "likelihood": 2,
                    "impact": 3,
                    "mitigation_strategy": "Monitor",
                }
            ],
            "psea_signoff": True,
            "sphere_standards_narrative": "",
        }
    )
    step4_result = validate_step4(step4, setup, {})
    # sphere_standards_narrative empty but sphere_standards_required=False for generic → no violation for sphere
    sphere_violations = [v for v in step4_result["violations"] if "sphere" in v["message"].lower()]
    assert len(sphere_violations) == 0, f"Generic should not require sphere narrative: {sphere_violations}"


def test_usaid_bha_vulnerable_quota_manifest_driven():
    """USAID/BHA requires >=50% vulnerable beneficiaries via manifest, not hardcoded."""
    from agent.proposal_v2_rules import normalize_step2, validate_step2

    setup = {"donor": "usaid_bha"}
    step2 = normalize_step2(
        {
            "humanitarian_context": "humanity neutrality impartiality operational independence",
            "needs_assessment": "vulnerability protection risk analysis for affected populations",
            "strategic_justification": "coordination cluster complementarity in the response",
            "beneficiaries": {
                "host_communities": {
                    "men_18_59": 90,
                    "women_18_59": 90,
                    "boys_0_17": 90,
                    "girls_0_17": 90,
                    "elderly_60_plus": 30,
                    "persons_with_disabilities": 30,
                },
                "idps": {
                    "men_18_59": 10,
                    "women_18_59": 10,
                    "boys_0_17": 10,
                    "girls_0_17": 10,
                    "elderly_60_plus": 3,
                    "persons_with_disabilities": 3,
                },
                "refugees_returnees": {
                    "men_18_59": 0,
                    "women_18_59": 0,
                    "boys_0_17": 0,
                    "girls_0_17": 0,
                    "elderly_60_plus": 0,
                    "persons_with_disabilities": 0,
                },
            },
        }
    )
    result = validate_step2(step2, setup)
    quota_violations = [
        v for v in result["violations"] if "50%" in v["message"] or "vulnerable" in v["message"].lower()
    ]
    assert len(quota_violations) > 0, "USAID/BHA should flag <50% vulnerable from manifest"


def test_unfpa_mandatory_tokens_enforced():
    """UNFPA requires 'srhr' and 'gbv' in executive intent."""
    from agent.proposal_v2_rules import normalize_setup, validate_setup

    setup = normalize_setup(
        {
            "project_title": "Protection Program for Women and Girls",
            "country": "Syria",
            "donor": "unfpa",
            "budget_amount": 200000,
            "budget_currency": "USD",
            "executive_intent": "This program addresses maternal health and dignity for displaced women and girls without using the required UNFPA-specific keywords in this text.",
            "sectors": ["Protection", "Health"],
        }
    )
    result = validate_setup(setup)
    token_violations = [v for v in result["violations"] if "concepts" in v["message"]]
    assert len(token_violations) > 0
    assert any("srhr" in v["message"] or "gbv" in v["message"] for v in token_violations)


def test_ocha_localization_subgrant_is_warning_not_violation():
    """OCHA localization subgrant <15% should be a warning, not a hard violation."""
    from agent.proposal_v2_rules import normalize_step4, validate_step4

    setup = {"donor": "ocha_cbpf"}
    # Budget with 0% localization (Category 4 = 0)
    step4 = normalize_step4(
        {
            "budget_items": [
                {
                    "category": 1,
                    "description": "Staff",
                    "unit_type": "month",
                    "quantity": 12,
                    "unit_cost": 3000,
                    "duration_frequency": 1,
                    "donor_grant_share": 36000,
                    "co_financing_share": 0,
                },
                {
                    "category": 5,
                    "description": "Overhead 5%",
                    "unit_type": "lump",
                    "quantity": 1,
                    "unit_cost": 1800,
                    "duration_frequency": 1,
                    "donor_grant_share": 1800,
                    "co_financing_share": 0,
                },
            ],
            "risks": [
                {
                    "category": "Security",
                    "risk_description": "Test",
                    "likelihood": 2,
                    "impact": 3,
                    "mitigation_strategy": "Monitor",
                }
            ],
            "psea_signoff": True,
            "sphere_standards_narrative": "Adheres to Sphere standards.",
        }
    )
    result = validate_step4(step4, setup, {})
    localization_warnings = [w for w in result["warnings"] if "localization" in w.lower() or "subgrant" in w.lower()]
    localization_violations = [
        v for v in result["violations"] if "localization" in v["message"].lower() or "subgrant" in v["message"].lower()
    ]
    assert len(localization_warnings) > 0, "Low localization should be a warning for OCHA"
    assert len(localization_violations) == 0, "Localization should NOT be a hard violation"
