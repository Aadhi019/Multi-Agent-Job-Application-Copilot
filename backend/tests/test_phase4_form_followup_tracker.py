import http.server
import socketserver
import threading
from pathlib import Path

from app.core.security import encrypt_secret
from app.models.user import User
from app.services.gmail import GmailService


MOCK_FORM_HTML = """<!doctype html>
<html>
  <body>
    <h1>Apply for Backend Engineer at MockCorp</h1>
    <form action="/submit" method="post">
      <label for="full_name">Full Name</label>
      <input id="full_name" name="full_name" type="text" />

      <label for="email">Email Address</label>
      <input id="email" name="email" type="email" />

      <label for="phone">Phone Number</label>
      <input id="phone" name="phone" type="tel" />

      <label for="linkedin">LinkedIn URL</label>
      <input id="linkedin" name="linkedin" type="url" />

      <label for="resume_file">Upload Resume</label>
      <input id="resume_file" name="resume_file" type="file" />

      <label for="why_role">Why are you interested in this role?</label>
      <textarea id="why_role" name="why_role"></textarea>

      <label for="unknown_code">Secret Referral Code</label>
      <input id="unknown_code" name="unknown_code" type="text" />

      <button type="submit" id="submit_btn">Submit Application</button>
    </form>
  </body>
</html>
"""


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(MOCK_FORM_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        return


def test_playwright_form_filler_against_local_mock_form(client, db_session):
    # Seed profile with links + resume
    client.put(
        "/api/profile",
        json={
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "skills": ["Python", "FastAPI", "Playwright"],
            "preferences": {
                "phone": "+1-555-0199",
                "linkedin_url": "https://linkedin.com/in/ada",
            },
            "master_resume_text": "Ada Lovelace\nSenior Python Engineer\nSkills: Python, FastAPI",
        },
    )

    server = socketserver.TCPServer(("127.0.0.1", 0), _QuietHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        job_res = client.post(
            "/api/jobs/import-url",
            json={
                "url": f"http://127.0.0.1:{port}/apply",
                "title": "Backend Engineer",
                "company": "MockCorp",
                "location": "Remote",
                "description": "Python and FastAPI backend services.",
            },
        )
        assert job_res.status_code == 201
        job_id = job_res.json()["id"]

        app_res = client.post("/api/applications", json={"job_id": job_id})
        assert app_res.status_code == 201
        app_id = app_res.json()["id"]

        fill_res = client.post(
            f"/api/applications/{app_id}/form-fill",
            json={"url": f"http://127.0.0.1:{port}/apply", "headless": True},
        )
        assert fill_res.status_code == 200
        report = fill_res.json()

        assert report["status"] == "ready_for_review"
        assert report["stopped_before_submit"] is True
        filled_types = {f["field_type"] for f in report["filled_fields"]}
        assert {"name", "email", "phone", "linkedin", "file", "free_text"}.issubset(filled_types)
        assert any(u["field_name"] == "unknown_code" for u in report["unfilled_fields"])
        assert len(report["screenshot_urls"]) >= 2

        for shot_path in report["screenshot_paths"]:
            assert Path(shot_path).exists()

        # Screenshot endpoint serves PNG safely
        shot_res = client.get(report["screenshot_urls"][-1])
        assert shot_res.status_code == 200
        assert shot_res.headers["content-type"].startswith("image/png")
    finally:
        server.shutdown()
        server.server_close()


def test_followup_draft_and_tracker_classification_with_mocked_gmail(client, db_session, monkeypatch):
    client.put(
        "/api/profile",
        json={"name": "Ada Lovelace", "email": "ada@example.com", "skills": ["Python", "FastAPI"]},
    )

    job_res = client.post(
        "/api/jobs/import-url",
        json={
            "url": "https://example.com/jobs/acme",
            "title": "Platform Engineer",
            "company": "Acme Corp",
            "location": "Remote",
            "description": "Python platform engineering.",
        },
    )
    app_res = client.post("/api/applications", json={"job_id": job_res.json()["id"]})
    app_id = app_res.json()["id"]

    # Draft follow-up email (pending approval)
    draft_res = client.post(
        f"/api/applications/{app_id}/follow-up",
        json={"followup_type": "after_applying", "to_email": "recruiter@acme.com"},
    )
    assert draft_res.status_code == 201
    draft_doc = draft_res.json()
    assert draft_doc["metadata"]["status"] == "pending_approval"

    # Simulate connected Gmail credentials and mock GmailService.create_draft (never sends!)
    user = db_session.query(User).first()
    user.gmail_credentials_encrypted = encrypt_secret('{"token": "fake"}')
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(
        GmailService,
        "create_draft",
        lambda self, u, db, to, subject, body: {"draft_id": "gmail-draft-999", "message_id": "msg-1"},
    )

    approve_draft = client.post(f"/api/applications/{app_id}/follow-up/{draft_doc['id']}/approve-draft")
    assert approve_draft.status_code == 200
    assert approve_draft.json()["metadata"]["status"] == "saved_to_gmail"
    assert approve_draft.json()["metadata"]["gmail_draft_id"] == "gmail-draft-999"

    # TrackerAgent syncs simulated Gmail inbox messages and updates application status -> interview
    sync_res = client.post(
        "/api/emails/sync",
        json={
            "simulated_messages": [
                {
                    "gmail_message_id": "gmail-msg-101",
                    "subject": "Interview Invitation from Acme Corp",
                    "from_email": "talent@acme.com",
                    "snippet": "We would love to schedule a call for your Platform Engineer application.",
                }
            ]
        },
    )
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["synced_count"] == 1
    assert sync_data["updated_applications"] == 1
    assert sync_data["emails"][0]["classification"] == "interview"

    updated_app = client.get(f"/api/applications/{app_id}")
    assert updated_app.status_code == 200
    assert updated_app.json()["status"] == "interview"
