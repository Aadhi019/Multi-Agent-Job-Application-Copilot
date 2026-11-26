import http.server
import json
import socketserver
import threading
from types import SimpleNamespace

from app.agents.cover_letter import CoverLetterAgent
from app.agents.follow_up import FollowUpAgent
from app.agents.interview_prep import InterviewPrepAgent
from app.agents.job_discovery import JobDiscoveryAgent, RawJobPosting
from app.agents.resume_tailor import ResumeTailorAgent
from app.agents.tracker import TrackerAgent
from app.models import Application, Job, User
from app.models.telemetry import AgentRun
from app.schemas.phase4 import TrackerSyncMessage
from app.services.groq import GroqService
from app.services.vector_store import VectorStoreService


def _make_mock_groq_seq(payloads: list[dict], tokens: int = 150) -> GroqService:
    queue = [json.dumps(p) for p in payloads]
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=queue.pop(0)))],
                    usage=SimpleNamespace(total_tokens=tokens),
                )
            )
        )
    )
    return GroqService(api_key="mock-key", model="llama-3.3-70b-versatile", client=fake_client)


def _make_mock_groq(payload_dict: dict, tokens: int = 150) -> GroqService:
    return _make_mock_groq_seq([payload_dict], tokens=tokens)


def test_all_agents_with_mocked_groq(client, db_session):
    client.put(
        "/api/profile",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "skills": ["Python", "FastAPI", "PostgreSQL"],
            "experience": [
                {
                    "company": "Analytical Engines",
                    "title": "Backend Engineer",
                    "start_date": "2022-01",
                    "end_date": "Present",
                    "location": "Remote",
                    "highlights": ["Built FastAPI APIs on PostgreSQL."],
                }
            ],
            "projects": [
                {
                    "name": "EngineX",
                    "description": "Async Python service",
                    "tech_stack": ["Python", "FastAPI"],
                    "url": "",
                    "highlights": ["Cut latency 30%."],
                }
            ],
            "master_resume_text": "Ada Lovelace\nSkills: Python, FastAPI, PostgreSQL",
        },
    )
    user = db_session.query(User).first()

    # 1. JobDiscoveryAgent with mocked Groq
    discovery_groq = _make_mock_groq(
        {
            "fit_score": 91,
            "fit_reason": "Matches Python, FastAPI, and PostgreSQL.",
            "matched_skills": ["Python", "FastAPI", "PostgreSQL"],
            "missing_skills": [],
        },
        tokens=110,
    )
    jd_agent = JobDiscoveryAgent(groq_service=discovery_groq)
    fit, tokens = jd_agent.score_fit(
        job=RawJobPosting("remotive", "Backend Engineer", "Acme", "Remote", "https://ex.com/1", "Python FastAPI"),
        skills=["Python", "FastAPI"],
        target_roles=["Backend Engineer"],
        location="Remote",
        remote_preference="remote",
        resume_text="Python FastAPI",
    )
    assert fit.fit_score == 91
    assert tokens == 110

    job = Job(
        user_id=user.id,
        source="mock",
        title="Backend Engineer",
        company="Acme",
        location="Remote",
        url="https://ex.com/1",
        description="Python FastAPI PostgreSQL",
        fit_score=91.0,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    app = Application(user_id=user.id, job_id=job.id, status="tailoring")
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)

    # 2. ResumeTailorAgent with mocked Groq (JDAnalyzer + Writer + Verifier)
    from app.models.evidence import ProfileFact
    from app.services.facts_extractor import rebuild_profile_facts

    facts = rebuild_profile_facts(db_session, user)
    exp_fact = next(f for f in facts if f.category == "experience_bullet")
    tailor_groq = _make_mock_groq_seq(
        [
            {
                "seniority": "mid",
                "keywords": ["Python", "FastAPI", "PostgreSQL"],
                "requirements": [
                    {"requirement": "FastAPI & PostgreSQL", "keywords": ["FastAPI", "PostgreSQL"], "priority": "required"}
                ],
            },
            {
                "summary": "Backend Engineer experienced in Python, FastAPI, and PostgreSQL.",
                "bullets": [
                    {
                        "section": "Experience",
                        "text": "Built FastAPI APIs on PostgreSQL.",
                        "fact_ids": [str(exp_fact.id)],
                        "jd_keywords_covered": ["FastAPI", "PostgreSQL"],
                    }
                ],
                "changes_made": ["Highlighted FastAPI and PostgreSQL skills."],
            },
            {
                "verifications": [
                    {"bullet_index": 0, "status": "verified", "reason": "Matches profile fact."}
                ]
            },
        ],
        tokens=100,
    )
    res_doc = ResumeTailorAgent(groq_service=tailor_groq).run(db_session, user, app, job)
    assert res_doc.doc_metadata["mode"] == "groq"
    assert res_doc.doc_metadata["keyword_coverage_score"] == 100.0

    # 3. CoverLetterAgent with mocked Groq
    cover_groq = _make_mock_groq(
        {
            "subject": "Backend Engineer Application",
            "greeting": "Dear Acme Team,",
            "paragraphs": ["Paragraph one.", "Paragraph two.", "Paragraph three."],
            "closing": "Sincerely,",
            "key_points_used": ["Python", "FastAPI"],
        },
        tokens=160,
    )
    cover_doc = CoverLetterAgent(groq_service=cover_groq).run(db_session, user, app, job, tone="formal")
    assert cover_doc.doc_metadata["mode"] == "groq"
    assert "Paragraph one." in cover_doc.content

    # 4. InterviewPrepAgent with mocked Groq
    prep_groq = _make_mock_groq(
        {
            "technical_questions": ["Explain FastAPI dependency injection."],
            "behavioral_questions": ["Tell me about EngineX."],
            "star_outlines": [
                {
                    "question": "Tell me about EngineX.",
                    "mapped_project_or_role": "EngineX",
                    "situation": "High API latency.",
                    "task": "Reduce response time.",
                    "action": "Profiled SQL queries.",
                    "result": "Cut latency 30%.",
                }
            ],
            "company_research_notes": ["Acme builds backend tools."],
            "questions_to_ask": ["How do you deploy FastAPI services?"],
        },
        tokens=210,
    )
    prep_doc = InterviewPrepAgent(groq_service=prep_groq).run(db_session, user, app, job)
    assert prep_doc.doc_metadata["mode"] == "groq"
    assert prep_doc.doc_metadata["structured"]["star_outlines"][0]["mapped_project_or_role"] == "EngineX"

    # 5. FollowUpAgent with mocked Groq
    followup_groq = _make_mock_groq(
        {
            "subject": "Following up on Backend Engineer",
            "body": "Hello Acme Team, following up on my application.",
            "recommended_send_window": "5 days",
        },
        tokens=90,
    )
    fup_doc = FollowUpAgent(groq_service=followup_groq).draft_followup(db_session, user, app, job)
    assert fup_doc.doc_metadata["mode"] == "groq"

    # 6. TrackerAgent with mocked Groq
    tracker_groq = _make_mock_groq(
        {
            "classification": "offer",
            "matched_company": "Acme",
            "confidence": 0.95,
            "summary": "Offer extended by Acme",
        },
        tokens=80,
    )
    sync_res = TrackerAgent(groq_service=tracker_groq).run(
        db_session,
        user,
        simulated_messages=[
            TrackerSyncMessage(
                gmail_message_id="m-offer-1",
                subject="Offer from Acme",
                snippet="We are pleased to extend an offer.",
            )
        ],
    )
    assert sync_res["updated_applications"] == 1
    db_session.refresh(app)
    assert app.status == "offer"

    runs = db_session.query(AgentRun).all()
    assert sum(r.tokens_used or 0 for r in runs) == (300 + 160 + 210 + 90 + 80)


def test_playwright_respects_captcha_gate_without_bypass(client):
    captcha_html = """<!doctype html><html><body>
    <form><div class="g-recaptcha"></div><input name="email" type="email"/></form>
    </body></html>"""

    class _CaptchaHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(captcha_html.encode("utf-8"))

        def log_message(self, format, *args):
            return

    server = socketserver.TCPServer(("127.0.0.1", 0), _CaptchaHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        job_res = client.post(
            "/api/jobs/import-url",
            json={
                "url": f"http://127.0.0.1:{port}/apply",
                "title": "Engineer",
                "company": "ProtectedCo",
                "description": "Python",
            },
        )
        app_res = client.post("/api/applications", json={"job_id": job_res.json()["id"]})
        app_id = app_res.json()["id"]

        fill_res = client.post(
            f"/api/applications/{app_id}/form-fill",
            json={"url": f"http://127.0.0.1:{port}/apply", "headless": True},
        )
        assert fill_res.status_code == 200
        report = fill_res.json()
        assert report["status"] == "blocked"
        assert "CAPTCHA" in report["blocked_reason"]
        assert report["stopped_before_submit"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_vector_store_semantic_fallback():
    vs = VectorStoreService()
    count = vs.upsert_chunks(
        "user-1",
        [
            {"id": "p1", "text": "Built FastAPI microservices with PostgreSQL and Docker", "metadata": {"type": "project"}},
            {"id": "p2", "text": "Designed mobile SwiftUI animations", "metadata": {"type": "project"}},
        ],
    )
    assert count == 2
    hits = vs.query("user-1", "Looking for FastAPI and PostgreSQL engineer", top_k=1)
    assert len(hits) == 1
    assert "FastAPI" in hits[0]["text"]
