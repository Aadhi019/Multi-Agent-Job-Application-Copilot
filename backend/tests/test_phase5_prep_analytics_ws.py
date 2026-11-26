from app.services.ws_manager import ws_manager


def test_interview_prep_and_analytics_summary(client):
    client.put(
        "/api/profile",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "skills": ["Python", "FastAPI", "PostgreSQL", "LangGraph"],
            "projects": [
                {
                    "name": "Copilot Graph",
                    "description": "Multi-agent workflow orchestrator",
                    "tech_stack": ["Python", "LangGraph"],
                    "url": "",
                    "highlights": ["Reduced review cycle time by 40%."],
                }
            ],
        },
    )

    job_res = client.post(
        "/api/jobs/import-url",
        json={
            "url": "https://example.com/jobs/ai-eng",
            "title": "Senior AI Engineer",
            "company": "DeepScale",
            "location": "Remote",
            "description": "Build multi-agent FastAPI services with PostgreSQL.",
        },
    )
    app_res = client.post("/api/applications", json={"job_id": job_res.json()["id"]})
    app_id = app_res.json()["id"]

    prep_res = client.post(f"/api/applications/{app_id}/interview-prep")
    assert prep_res.status_code == 201
    prep_doc = prep_res.json()
    structured = prep_doc["metadata"]["structured"]
    assert len(structured["technical_questions"]) >= 3
    assert len(structured["star_outlines"]) >= 1
    assert structured["star_outlines"][0]["mapped_project_or_role"] == "Copilot Graph"

    # Update status to interview so response rate > 0
    client.patch(f"/api/applications/{app_id}/status", json={"status": "interview"})

    analytics_res = client.get("/api/analytics/summary")
    assert analytics_res.status_code == 200
    summary = analytics_res.json()
    assert summary["total_jobs"] >= 1
    assert summary["total_applications"] >= 1
    assert summary["counts_by_status"]["interview"] >= 1
    assert summary["response_rate"] == 100.0
    agent_names = {m["agent_name"] for m in summary["agent_metrics"]}
    assert "InterviewPrepAgent" in agent_names


def test_websocket_run_progress_streaming(client):
    ws_manager.emit_sync(
        run_id="demo-run-1",
        agent_name="ResumeTailorAgent",
        step="completed",
        status="success",
        message="Tailored resume v1 ready.",
    )
    with client.websocket_connect("/ws/runs/demo-run-1") as websocket:
        data = websocket.receive_json()
        assert data["run_id"] == "demo-run-1"
        assert data["agent_name"] == "ResumeTailorAgent"
        assert data["status"] == "success"

        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["type"] == "pong"
