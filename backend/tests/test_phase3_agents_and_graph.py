from app.agents.job_discovery import JobDiscoveryAgent, RawJobPosting
from app.models.telemetry import AgentRun


def _seed_profile(client):
    res = client.put(
        "/api/profile",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "LangGraph"],
            "experience": [
                {
                    "company": "Analytical Engines Ltd",
                    "title": "Senior Backend Engineer",
                    "start_date": "2022-01",
                    "end_date": "Present",
                    "location": "Remote",
                    "highlights": [
                        "Built FastAPI microservices backed by PostgreSQL and Docker.",
                        "Designed multi-agent LangGraph workflows for document processing.",
                    ],
                }
            ],
            "projects": [
                {
                    "name": "Copilot Engine",
                    "description": "Stateful LLM orchestrator with human-in-the-loop checkpoints.",
                    "tech_stack": ["Python", "LangGraph", "PostgreSQL"],
                    "url": "https://github.com/ada/copilot",
                    "highlights": ["Cut processing latency by 35%."],
                }
            ],
            "education": [{"institution": "University of London", "degree": "BSc CS", "graduation_year": "2019", "gpa": ""}],
            "master_resume_text": (
                "Ada Lovelace\nSenior Backend Engineer\n"
                "Skills: Python, FastAPI, PostgreSQL, Docker, LangGraph\n"
                "Built FastAPI microservices backed by PostgreSQL and Docker."
            ),
        },
    )
    assert res.status_code == 200


def test_job_discovery_deduplicates_and_logs_agent_run(client, db_session, monkeypatch):
    _seed_profile(client)

    sample_postings = [
        RawJobPosting(
            source="remotive",
            title="Senior Python FastAPI Engineer",
            company="Acme AI",
            location="Remote",
            url="https://jobs.example.com/1",
            description="Looking for Python, FastAPI, PostgreSQL, and Docker expertise.",
        ),
        RawJobPosting(
            source="remotive",
            title="Senior Python FastAPI Engineer",
            company="Acme AI",
            location="Remote",
            url="https://jobs.example.com/1",  # duplicate URL
            description="Duplicate posting.",
        ),
        RawJobPosting(
            source="arbeitnow",
            title="Frontend Designer",
            company="Pixel Studio",
            location="Berlin",
            url="https://jobs.example.com/2",
            description="Figma and CSS visual design.",
        ),
    ]
    monkeypatch.setattr(JobDiscoveryAgent, "fetch_remotive", lambda self, q, limit=15: sample_postings[:2])
    monkeypatch.setattr(JobDiscoveryAgent, "fetch_arbeitnow", lambda self, q, limit=15: [sample_postings[2]])

    res = client.post(
        "/api/jobs/discover",
        json={"query": "Python", "sources": ["remotive", "arbeitnow"], "limit": 10},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["discovered_count"] == 2
    assert body["deduplicated_count"] == 1
    # Ranked descending by fit score (Python FastAPI role should beat Frontend Designer)
    assert body["jobs"][0]["title"] == "Senior Python FastAPI Engineer"
    assert body["jobs"][0]["fit_score"] > body["jobs"][1]["fit_score"]

    runs = db_session.query(AgentRun).filter(AgentRun.agent_name == "JobDiscoveryAgent").all()
    assert len(runs) == 1
    assert runs[0].status == "success"


def test_langgraph_apply_workflow_pauses_at_awaiting_approval_and_resumes(client, db_session):
    _seed_profile(client)

    job_res = client.post(
        "/api/jobs/import-url",
        json={
            "url": "https://example.com/jobs/backend-ai",
            "title": "AI Backend Engineer",
            "company": "NeuralWorks",
            "location": "Remote",
            "description": "Need Python, FastAPI, PostgreSQL, LangGraph, and Kubernetes.",
        },
    )
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]

    # Start LangGraph apply_to_job workflow -> pauses at awaiting_approval
    app_res = client.post(
        "/api/applications",
        json={"job_id": job_id, "cover_letter_tone": "concise"},
    )
    assert app_res.status_code == 201
    detail = app_res.json()
    assert detail["status"] == "awaiting_approval"
    app_id = detail["id"]

    doc_types = {d["type"] for d in detail["documents"]}
    assert doc_types == {"resume", "cover_letter"}

    resume_doc = next(d for d in detail["documents"] if d["type"] == "resume")
    # Truthfulness check: Kubernetes is NOT in Ada's profile, so it must be in missing_keywords, not skills_highlighted
    assert "Kubernetes" in resume_doc["metadata"]["missing_keywords"]
    assert "Kubernetes" not in resume_doc["metadata"]["structured"]["skills_highlighted"]

    # Downloadable DOCX, PDF, and MD endpoints
    for fmt in ("docx", "pdf", "md"):
        dl = client.get(f"/api/applications/{app_id}/resume/download?format={fmt}")
        assert dl.status_code == 200
        assert len(dl.content) > 50

    # Edit cover letter in UI -> creates v2
    edit_res = client.put(
        f"/api/applications/{app_id}/cover-letter",
        json={"content": "Edited cover letter text.", "tone": "friendly"},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["version"] == 2

    # Human approves paused LangGraph checkpoint -> ready_to_submit
    approve_res = client.post(
        f"/api/applications/{app_id}/approve",
        json={"feedback": "Looks accurate and ready."},
    )
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "ready_to_submit"

    # Verify agent_runs logged both ResumeTailorAgent and CoverLetterAgent
    runs_res = client.get("/api/agent-runs")
    assert runs_res.status_code == 200
    agent_names = {r["agent_name"] for r in runs_res.json()}
    assert {"JobDiscoveryAgent", "ResumeTailorAgent", "CoverLetterAgent"}.issubset(agent_names)


def test_render_resume_pdf_sanitizes_unicode_hyphens():
    from app.agents.resume_tailor import render_resume_pdf

    md = (
        "# Jane Doe\n"
        "## Summary\n"
        "AI\u2011native engineer with hands\u2011on end\u2011to\u2011end & R&D <3 experience.\n"
        "- Built multi\u2011agent workflows \u2014 99% uptime\n"
    )
    pdf_bytes = render_resume_pdf(md)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500
