import json
from types import SimpleNamespace

from app.agents.resume_tailor import ResumeTailorAgent
from app.models import Application, Job, User
from app.models.evidence import ProfileFact, ResumeBullet
from app.services.groq import GroqService


def _seq_mock_groq(responses: list[dict]) -> GroqService:
    queue = [json.dumps(r) for r in responses]
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=queue.pop(0)))],
                    usage=SimpleNamespace(total_tokens=100),
                )
            )
        )
    )
    return GroqService(api_key="mock-key", client=fake_client)


def test_profile_facts_extraction_and_crud(client, db_session):
    res = client.put(
        "/api/profile",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "skills": ["Python", "FastAPI"],
            "experience": [
                {
                    "company": "Analytical Ltd",
                    "title": "Backend Engineer",
                    "start_date": "2023-01",
                    "end_date": "Present",
                    "location": "Remote",
                    "highlights": ["Built FastAPI services with PostgreSQL."],
                }
            ],
        },
    )
    assert res.status_code == 200

    facts_res = client.get("/api/profile/facts")
    assert facts_res.status_code == 200
    facts = facts_res.json()
    assert len(facts) >= 3
    assert any("Built FastAPI services with PostgreSQL." in f["text"] for f in facts)

    # Create manual fact
    add_res = client.post(
        "/api/profile/facts",
        json={"category": "certification", "text": "AWS Solutions Architect", "source_section": "Certs"},
    )
    assert add_res.status_code == 201
    fid = add_res.json()["id"]

    # Update & delete fact
    upd_res = client.put(f"/api/profile/facts/{fid}", json={"text": "AWS Certified Developer"})
    assert upd_res.status_code == 200
    assert upd_res.json()["text"] == "AWS Certified Developer"

    del_res = client.delete(f"/api/profile/facts/{fid}")
    assert del_res.status_code == 204


def test_verifier_catches_and_removes_injected_fabricated_skill(client, db_session):
    client.put(
        "/api/profile",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "skills": ["Python", "FastAPI"],
            "experience": [
                {
                    "company": "Analytical Ltd",
                    "title": "Backend Engineer",
                    "start_date": "2023-01",
                    "end_date": "Present",
                    "location": "Remote",
                    "highlights": ["Built FastAPI services with PostgreSQL."],
                }
            ],
        },
    )
    user = db_session.query(User).first()
    fact = db_session.query(ProfileFact).filter(ProfileFact.category == "experience_bullet").first()
    assert fact is not None

    job = Job(
        user_id=user.id,
        source="test",
        title="Platform Engineer",
        company="CloudCo",
        location="Remote",
        url="https://example.com/1",
        description="Need FastAPI and Kubernetes.",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    app = Application(user_id=user.id, job_id=job.id, status="tailoring")
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)

    # Sequence: JDAnalyzer -> Writer1 (hallucinates Kubernetes + 400%) -> Verifier1 -> Writer2 (still hallucinates) -> Verifier2
    groq = _seq_mock_groq(
        [
            {
                "seniority": "mid",
                "keywords": ["FastAPI", "Kubernetes"],
                "requirements": [
                    {"requirement": "FastAPI APIs", "keywords": ["FastAPI"], "priority": "required"},
                    {"requirement": "Kubernetes orchestration", "keywords": ["Kubernetes"], "priority": "required"},
                ],
            },
            {
                "summary": "Backend engineer.",
                "bullets": [
                    {
                        "section": "Experience",
                        "text": "Built FastAPI services with PostgreSQL.",
                        "fact_ids": [str(fact.id)],
                        "jd_keywords_covered": ["FastAPI"],
                    },
                    {
                        "section": "Experience",
                        "text": "Managed Kubernetes clusters reducing latency by 400%.",
                        "fact_ids": [str(fact.id)],
                        "jd_keywords_covered": ["Kubernetes"],
                    },
                ],
                "changes_made": ["Tailored bullets"],
            },
            {
                "verifications": [
                    {"bullet_index": 0, "status": "verified", "reason": "Matches fact."},
                    {"bullet_index": 1, "status": "unsupported", "reason": "Kubernetes and 400% not in facts."},
                ]
            },
            {
                "summary": "Backend engineer.",
                "bullets": [
                    {
                        "section": "Experience",
                        "text": "Built FastAPI services with PostgreSQL.",
                        "fact_ids": [str(fact.id)],
                        "jd_keywords_covered": ["FastAPI"],
                    },
                    {
                        "section": "Experience",
                        "text": "Deployed Kubernetes workloads.",
                        "fact_ids": [str(fact.id)],
                        "jd_keywords_covered": ["Kubernetes"],
                    },
                ],
                "changes_made": ["Retried bullets"],
            },
            {
                "verifications": [
                    {"bullet_index": 0, "status": "verified", "reason": "Matches fact."},
                    {"bullet_index": 1, "status": "unsupported", "reason": "Kubernetes still not in facts."},
                ]
            },
        ]
    )

    doc = ResumeTailorAgent(groq_service=groq).run(db_session, user, app, job)
    report = doc.doc_metadata["verification_report"]
    assert report["unsupported_removed_count"] == 1
    assert report["verified_count"] == 1
    assert report["hallucination_rate"] == 0.5
    assert "Kubernetes" not in doc.content
    assert "Kubernetes orchestration" in report["missing_requirements"]

    # Check GET /api/documents/{id}/verification
    ver_res = client.get(f"/api/documents/{doc.id}/verification")
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert len(ver_data["bullets"]) == 2
    verified_bullet = next(b for b in ver_data["bullets"] if b["status"] == "verified")
    assert len(verified_bullet["evidence_facts"]) == 1
    assert verified_bullet["evidence_facts"][0]["id"] == str(fact.id)

    # Check POST /api/documents/{id}/bullets/{bullet_id}/regenerate
    regen_res = client.post(f"/api/documents/{doc.id}/bullets/{verified_bullet['id']}/regenerate")
    assert regen_res.status_code == 200
    assert regen_res.json()["status"] in ("verified", "rephrased_ok")
