import json
import pytest
from unittest.mock import patch
import auth
import server

@pytest.fixture
def app():
    return server.app

@pytest.fixture
def client(app):
    return app.test_client()

class TestProposalsAPI:
    def test_get_proposals_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), \
             patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/proposals")
            assert resp.status_code == 401

    def test_create_proposal_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), \
             patch.object(auth, "_api_key", return_value=""):
            resp = client.post("/api/proposals/new", json={"country": "Sudan"})
            assert resp.status_code == 401

    def test_create_and_get_proposal_flow(self, client):
        fake_token = {"uid": "test-user-123", "role": "free"}
        with patch.object(auth, "_dev_mode", return_value=False), \
             patch.object(auth, "verify_firebase_token", return_value=fake_token):
            
            # 1. Create a proposal
            create_resp = client.post(
                "/api/proposals/new",
                headers={"Authorization": "Bearer token"},
                json={
                    "title": "WASH South Sudan",
                    "country": "Sudan",
                    "event": "Sudan Conflict 2026",
                    "themes": ["WASH", "Health"],
                    "donor": "ECHO"
                }
            )
            assert create_resp.status_code == 201
            data = json.loads(create_resp.data)
            prop_id = data["id"]
            assert data["title"] == "WASH South Sudan"
            assert data["country"] == "Sudan"
            
            # 2. Get the proposal details
            get_resp = client.get(
                f"/api/proposals/{prop_id}",
                headers={"Authorization": "Bearer token"}
            )
            assert get_resp.status_code == 200
            get_data = json.loads(get_resp.data)
            assert get_data["id"] == prop_id
            assert get_data["donor"] == "ECHO"

            # 3. Update fields
            update_resp = client.put(
                f"/api/proposals/{prop_id}",
                headers={"Authorization": "Bearer token"},
                json={
                    "title": "WASH South Sudan v2",
                    "donor": "USAID"
                }
            )
            assert update_resp.status_code == 200
            
            # Verify update
            get_resp2 = client.get(
                f"/api/proposals/{prop_id}",
                headers={"Authorization": "Bearer token"}
            )
            get_data2 = json.loads(get_resp2.data)
            assert get_data2["title"] == "WASH South Sudan v2"
            assert get_data2["donor"] == "USAID"
            
            # 4. List proposals
            list_resp = client.get(
                "/api/proposals",
                headers={"Authorization": "Bearer token"}
            )
            assert list_resp.status_code == 200
            list_data = json.loads(list_resp.data)
            assert len(list_data) >= 1
            assert any(p["id"] == prop_id for p in list_data)
            
            # 5. Delete proposal
            delete_resp = client.delete(
                f"/api/proposals/{prop_id}",
                headers={"Authorization": "Bearer token"}
            )
            assert delete_resp.status_code == 200
            
            # Verify deleted
            get_resp_deleted = client.get(
                f"/api/proposals/{prop_id}",
                headers={"Authorization": "Bearer token"}
            )
            assert get_resp_deleted.status_code == 404

    def test_llm_generation_flows(self, client):
        fake_token = {"uid": "test-user-123", "role": "free"}
        with patch.object(auth, "_dev_mode", return_value=False), \
             patch.object(auth, "verify_firebase_token", return_value=fake_token), \
             patch("reliefweb_api.vector_store.VectorStore") as mock_vector_store:
             
            # Create a test proposal
            create_resp = client.post(
                "/api/proposals/new",
                headers={"Authorization": "Bearer token"},
                json={
                    "title": "WASH Sudan",
                    "country": "Sudan",
                    "event": "Sudan Conflict",
                    "themes": ["WASH"],
                    "donor": "ECHO"
                }
            )
            assert create_resp.status_code == 201
            prop_id = json.loads(create_resp.data)["id"]

            # Mock ToC generation
            mock_toc_response = '[{"level": "impact", "text": "Enhanced health"}, {"level": "outcome", "text": "Access to WASH"}, {"level": "output", "text": "Water points build"}, {"level": "activity", "text": "Drill wells"}]'
            with patch("sitrep.llm_client.chat", return_value=mock_toc_response):
                toc_resp = client.post(
                    f"/api/proposals/{prop_id}/generate-toc",
                    headers={"Authorization": "Bearer token"}
                )
                assert toc_resp.status_code == 200
                toc_data = json.loads(toc_resp.data)
                assert len(toc_data) == 4
                assert toc_data[0]["text"] == "Enhanced health"

            # Mock Logframe generation
            mock_lf_response = '{"goal": "G1. Health improved", "outcomes": "OC1. WASH access", "outputs": "O1. Wells built", "activities": "A1. Drill wells"}'
            with patch("sitrep.llm_client.chat", return_value=mock_lf_response):
                lf_resp = client.post(
                    f"/api/proposals/{prop_id}/generate-logframe",
                    headers={"Authorization": "Bearer token"}
                )
                assert lf_resp.status_code == 200
                lf_data = json.loads(lf_resp.data)
                assert lf_data["goal"] == "G1. Health improved"

            # Mock Advisor Chat critique and command execution
            from unittest.mock import MagicMock
            from langchain_core.messages import AIMessage
            mock_advisor_response = 'I suggest updating the output node. <cmd>{"action": "update_toc", "index": 2, "text": "10 modern wells drilled"}</cmd>'
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [AIMessage(content=mock_advisor_response)]}
            
            with patch("server._get_agent", return_value=mock_agent):
                adv_resp = client.post(
                    f"/api/proposals/{prop_id}/advisor/chat",
                    headers={"Authorization": "Bearer token"},
                    json={"message": "Critique my ToC outputs."}
                )
                assert adv_resp.status_code == 200
                adv_data = json.loads(adv_resp.data)
                assert "I suggest" in adv_data["response"]
                assert adv_data["command"]["action"] == "update_toc"

                # Verify index 2 is updated to "10 modern wells drilled" in DB
                get_resp = client.get(
                    f"/api/proposals/{prop_id}",
                    headers={"Authorization": "Bearer token"}
                )
                get_data = json.loads(get_resp.data)
                assert get_data["toc"][2]["text"] == "10 modern wells drilled"

            # Mock Narrative generation
            mock_narrative_response = "## Needs Assessment\\nRecent data shows..."
            with patch("sitrep.llm_client.chat", return_value=mock_narrative_response):
                narr_resp = client.post(
                    f"/api/proposals/{prop_id}/generate-narrative",
                    headers={"Authorization": "Bearer token"}
                )
                assert narr_resp.status_code == 200
                narr_data = json.loads(narr_resp.data)
                assert "Recent data" in narr_data["narrative"]

    def test_proposal_chunks_endpoint(self, client):
        fake_token = {"uid": "test-user-123", "role": "free"}
        with patch.object(auth, "_dev_mode", return_value=False), \
             patch.object(auth, "verify_firebase_token", return_value=fake_token):
             
            # 1. Create proposal
            create_resp = client.post(
                "/api/proposals/new",
                headers={"Authorization": "Bearer token"},
                json={
                    "title": "Conflict Relief Sudan",
                    "country": "Sudan",
                    "event": "Sudan Conflict",
                    "themes": ["WASH"],
                    "donor": "ECHO"
                }
            )
            assert create_resp.status_code == 201
            prop_id = json.loads(create_resp.data)["id"]

            # 2. Get chunks mock test
            mock_chunks = [{"text": "Water points destroyed in Darfur", "title": "Sudan sitrep", "date": "2026-04-10", "themes": "WASH"}]
            with patch("sitrep.chroma_adapter.ChromaAdapter") as mock_adapter_class:
                mock_adapter = mock_adapter_class.return_value
                mock_adapter.get_chunks_by_country_and_themes.return_value = mock_chunks
                chunks_resp = client.get(
                    f"/api/proposals/{prop_id}/chunks",
                    headers={"Authorization": "Bearer token"}
                )
                assert chunks_resp.status_code == 200
                chunks_data = json.loads(chunks_resp.data)
                assert len(chunks_data) == 1
                assert chunks_data[0]["text"] == "Water points destroyed in Darfur"

    def test_proposal_advisor_agent_chat(self, client):
        from unittest.mock import MagicMock
        from langchain_core.messages import AIMessage
        
        fake_token = {"uid": "test-user-123", "role": "admin"}
        with patch.object(auth, "_dev_mode", return_value=False), \
             patch.object(auth, "verify_firebase_token", return_value=fake_token):
             
            # 1. Create proposal
            create_resp = client.post(
                "/api/proposals/new",
                headers={"Authorization": "Bearer token"},
                json={
                    "title": "Advisor Test Proposal",
                    "country": "Sudan",
                    "event": "Sudan Conflict",
                    "themes": ["WASH"],
                    "donor": "ECHO"
                }
            )
            assert create_resp.status_code == 201
            prop_id = json.loads(create_resp.data)["id"]

            # 2. Mock Agent response with ToC update
            mock_response_message = AIMessage(
                content="Critique processed. <cmd>{\"action\": \"update_toc\", \"index\": 0, \"text\": \"Custom Goal\"}</cmd>"
            )
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [mock_response_message]}
            
            with patch("server._get_agent", return_value=mock_agent):
                chat_resp = client.post(
                    f"/api/proposals/{prop_id}/advisor/chat",
                    headers={"Authorization": "Bearer token"},
                    json={"message": "Please update my ToC goal."}
                )
                assert chat_resp.status_code == 200
                chat_data = json.loads(chat_resp.data)
                assert "Critique processed." in chat_data["response"]
                assert chat_data["command"]["action"] == "update_toc"
                
                # Check DB updated index 0
                get_resp = client.get(
                    f"/api/proposals/{prop_id}",
                    headers={"Authorization": "Bearer token"}
                )
                get_data = json.loads(get_resp.data)
                assert get_data["toc"][0]["text"] == "Custom Goal"

            # 3. Check history endpoint
            hist_resp = client.get(
                f"/api/proposals/{prop_id}/advisor/history",
                headers={"Authorization": "Bearer token"}
            )
            assert hist_resp.status_code == 200
            hist_data = json.loads(hist_resp.data)
            assert len(hist_data) >= 2
            assert hist_data[-2]["role"] == "user"
            assert hist_data[-1]["role"] == "assistant"



