"""Report real-time metrics from live database runs (jobs, tailoring coverage, latency, success rate).

Usage:
    cd backend
    python -m scripts.evaluate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import SessionLocal
from app.models import Application, Document, Job
from app.models.telemetry import AgentRun


def collect_realtime_metrics() -> dict[str, object]:
    """Compute real-time metrics from actual database records."""
    with SessionLocal() as db:
        jobs = db.scalars(select(Job)).all()
        apps = db.scalars(select(Application)).all()
        resume_docs = db.scalars(select(Document).where(Document.type == "resume")).all()
        runs = db.scalars(select(AgentRun)).all()

        tailor_runs = [r for r in runs if r.agent_name == "ResumeTailorAgent" and r.latency_ms is not None]
        avg_tailor_ms = (
            round(sum(r.latency_ms or 0 for r in tailor_runs) / len(tailor_runs), 2)
            if tailor_runs
            else None
        )

        coverages = [
            float((d.doc_metadata or {}).get("keyword_coverage_score"))
            for d in resume_docs
            if (d.doc_metadata or {}).get("keyword_coverage_score") is not None
        ]
        avg_coverage = round(sum(coverages) / len(coverages), 2) if coverages else None

        total_runs = len(runs)
        success_runs = sum(1 for r in runs if r.status in ("success", "partial"))
        success_rate = round((success_runs / total_runs) * 100.0, 2) if total_runs else None

        return {
            "total_jobs": len(jobs),
            "total_applications": len(apps),
            "total_agent_runs": total_runs,
            "agent_success_rate_pct": success_rate,
            "avg_tailoring_time_ms": avg_tailor_ms,
            "avg_keyword_coverage_pct": avg_coverage,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Report real-time Job Application Copilot metrics.")
    parser.add_argument("--json", action="store_true", help="Output metrics as JSON.")
    args = parser.parse_args()

    report = collect_realtime_metrics()
    if args.json:
        print(json.dumps(report, indent=2))
        return

    sr = f"{report['agent_success_rate_pct']}%" if report["agent_success_rate_pct"] is not None else "N/A"
    tt = f"{report['avg_tailoring_time_ms']} ms" if report["avg_tailoring_time_ms"] is not None else "N/A"
    kc = f"{report['avg_keyword_coverage_pct']}%" if report["avg_keyword_coverage_pct"] is not None else "N/A"

    print("=== Real-Time Job Application Copilot Metrics ===")
    print(f"Discovered jobs          : {report['total_jobs']}")
    print(f"Applications             : {report['total_applications']}")
    print(f"Total agent runs         : {report['total_agent_runs']}")
    print(f"Agent success rate       : {sr}")
    print(f"Avg tailoring time       : {tt}")
    print(f"Avg keyword coverage     : {kc}")


if __name__ == "__main__":
    main()
