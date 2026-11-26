import io

from docx import Document as DocxDocument


def test_get_and_update_profile(client):
    res = client.get("/api/profile")
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "copilot@local.dev"
    assert data["skills"] == []

    update_payload = {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "preferences": {
            "target_roles": ["AI Engineer"],
            "preferred_locations": ["Remote"],
            "remote_preference": "remote",
            "cover_letter_tone": "concise",
            "job_sources": ["remotive"],
            "phone": "+1-555-0100",
            "linkedin_url": "https://linkedin.com/in/ada",
            "github_url": "https://github.com/ada",
            "portfolio_url": "",
        },
    }
    put_res = client.put("/api/profile", json=update_payload)
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["name"] == "Ada Lovelace"
    assert updated["skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert updated["preferences"]["cover_letter_tone"] == "concise"


def test_upload_txt_resume_heuristic_fallback(client):
    resume_text = (
        "Grace Hopper\n"
        "grace@navy.mil\n"
        "Skills\n"
        "Python, FastAPI, Docker, PostgreSQL\n"
        "Education\n"
        "Yale University\n"
        "PhD Mathematics\n"
    )
    res = client.post(
        "/api/profile/resume",
        files={"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")},
        data={"auto_populate": "true"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["parser_mode"] == "heuristic"
    assert body["extracted_chars"] > 20
    assert body["profile"]["name"] == "Grace Hopper"
    assert body["profile"]["email"] == "grace@navy.mil"
    assert "Python" in body["profile"]["skills"]


def test_upload_docx_resume(client):
    doc = DocxDocument()
    doc.add_paragraph("Alan Turing")
    doc.add_paragraph("alan@bletchley.org")
    doc.add_paragraph("Skills")
    doc.add_paragraph("Algorithms, Python, Cryptography")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    res = client.post(
        "/api/profile/resume",
        files={
            "file": (
                "alan_resume.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"auto_populate": "true"},
    )
    assert res.status_code == 200
    body = res.json()
    assert "Alan Turing" in body["profile"]["master_resume_text"]
    assert "Cryptography" in body["profile"]["skills"]


def test_upload_unsupported_file_returns_400(client):
    res = client.post(
        "/api/profile/resume",
        files={"file": ("resume.exe", b"binary", "application/octet-stream")},
    )
    assert res.status_code == 400


def test_updating_profile_rescores_saved_jobs(client):
    # Start with unrelated skills and import a Python/FastAPI job
    client.put("/api/profile", json={"skills": ["Photoshop"], "master_resume_text": "Graphic designer."})
    job_res = client.post(
        "/api/jobs/import-url",
        json={
            "url": "https://example.com/jobs/python-fastapi",
            "title": "Python FastAPI Engineer",
            "company": "ApiCo",
            "location": "Remote",
            "description": "Build FastAPI services with PostgreSQL and Docker.",
        },
    )
    assert job_res.status_code == 201
    initial_score = job_res.json()["fit_score"]

    # Update profile/resume with matching skills -> saved job score must increase automatically
    client.put(
        "/api/profile",
        json={
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "master_resume_text": "Senior Python FastAPI Engineer with PostgreSQL and Docker.",
        },
    )
    jobs_after = client.get("/api/jobs").json()
    assert jobs_after[0]["fit_score"] > initial_score
