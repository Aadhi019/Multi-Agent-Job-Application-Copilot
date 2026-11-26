from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import record_agent_run
from app.agents.prompts import load_prompt
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobFitScoreOutput
from app.services.groq import GroqService, GroqServiceError

logger = logging.getLogger(__name__)

USER_AGENT = "JobApplicationCopilot/1.0 (+https://github.com/local/job-copilot)"


@dataclass
class RawJobPosting:
    source: str
    title: str
    company: str
    location: str
    url: str
    description: str


def _strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def _normalize_dedup_key(title: str, company: str) -> str:
    clean = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return f"{clean(title)}::{clean(company)}"


class JobDiscoveryAgent:
    """Discovers jobs from public APIs/RSS feeds, deduplicates, scores fit, and stores results."""

    name = "JobDiscoveryAgent"

    def __init__(self, groq_service: GroqService | None = None) -> None:
        self.groq = groq_service or GroqService()

    def fetch_remotive(self, search_query: str = "", limit: int = 15) -> list[RawJobPosting]:
        params: dict[str, Any] = {"limit": limit}
        if search_query:
            params["search"] = search_query
        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get("https://remotive.com/api/remote-jobs", params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[RawJobPosting] = []
        for item in data.get("jobs", [])[:limit]:
            results.append(
                RawJobPosting(
                    source="remotive",
                    title=item.get("title", "Untitled Role").strip(),
                    company=item.get("company_name", "Unknown Company").strip(),
                    location=item.get("candidate_required_location", "Remote").strip() or "Remote",
                    url=item.get("url", "").strip(),
                    description=_strip_html(item.get("description", ""))[:5000],
                )
            )
        return results

    def fetch_arbeitnow(self, search_query: str = "", limit: int = 15) -> list[RawJobPosting]:
        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get("https://www.arbeitnow.com/api/job-board-api")
            resp.raise_for_status()
            data = resp.json()

        query_terms = [t.lower() for t in search_query.split() if len(t) > 1]
        results: list[RawJobPosting] = []
        for item in data.get("data", []):
            title = item.get("title", "Untitled Role").strip()
            desc = _strip_html(item.get("description", ""))
            haystack = f"{title} {desc} {' '.join(item.get('tags', []))}".lower()
            if query_terms and not any(term in haystack for term in query_terms):
                continue
            results.append(
                RawJobPosting(
                    source="arbeitnow",
                    title=title,
                    company=item.get("company_name", "Unknown Company").strip(),
                    location=item.get("location", "Remote" if item.get("remote") else "").strip(),
                    url=item.get("url", "").strip(),
                    description=desc[:5000],
                )
            )
            if len(results) >= limit:
                break
        return results

    def fetch_himalayas(
        self, search_query: str = "", location: str = "", limit: int = 15
    ) -> list[RawJobPosting]:
        loc_terms = [t.strip().lower() for t in location.split(",") if t.strip()]
        query_terms = [t.lower() for t in search_query.split() if len(t) > 1]
        results: list[RawJobPosting] = []
        cursor: str | None = None

        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            for _ in range(4):
                params: dict[str, Any] = {"limit": 20}
                if cursor:
                    params["cursor"] = cursor
                resp = client.get("https://himalayas.app/jobs/api", params=params)
                resp.raise_for_status()
                payload = resp.json()
                jobs_batch = payload.get("jobs", [])
                if not jobs_batch:
                    break

                for item in jobs_batch:
                    title = str(item.get("title") or "Untitled Role").strip()
                    desc = _strip_html(str(item.get("description") or item.get("excerpt") or ""))
                    restrictions = [str(r) for r in (item.get("locationRestrictions") or []) if r]
                    loc_str = ", ".join(restrictions) if restrictions else "Worldwide (Remote)"

                    if loc_terms:
                        loc_hay = loc_str.lower()
                        is_global = not restrictions or "worldwide" in loc_hay or "anywhere" in loc_hay
                        if not is_global and not any(t in loc_hay for t in loc_terms):
                            continue

                    haystack = f"{title} {desc}".lower()
                    if query_terms and not any(t in haystack for t in query_terms):
                        continue

                    url = str(item.get("applicationLink") or item.get("guid") or "").strip()
                    if not url:
                        continue
                    results.append(
                        RawJobPosting(
                            source="himalayas",
                            title=title,
                            company=str(item.get("companyName") or "Unknown Company").strip(),
                            location=loc_str,
                            url=url,
                            description=desc[:5000],
                        )
                    )
                    if len(results) >= limit:
                        return results

                cursor = payload.get("nextCursor")
                if not cursor:
                    break
        return results

    def fetch_jobicy(
        self, search_query: str = "", location: str = "", limit: int = 15
    ) -> list[RawJobPosting]:
        params: dict[str, Any] = {"count": min(max(limit, 5), 50)}
        if search_query:
            params["tag"] = search_query.split()[0].lower()
        loc_lower = location.lower()
        if any(k in loc_lower for k in ("india", "apac", "asia", "singapore", "australia")):
            params["geo"] = "apac"
        elif location:
            params["geo"] = "anywhere"

        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get("https://jobicy.com/api/v2/remote-jobs", params=params)
            if resp.status_code == 400 and "tag" in params:
                params.pop("tag")
                resp = client.get("https://jobicy.com/api/v2/remote-jobs", params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[RawJobPosting] = []
        for item in data.get("jobs", [])[:limit]:
            results.append(
                RawJobPosting(
                    source="jobicy",
                    title=str(item.get("jobTitle") or "Untitled Role").strip(),
                    company=str(item.get("companyName") or "Unknown Company").strip(),
                    location=str(item.get("jobGeo") or "Remote").strip(),
                    url=str(item.get("url") or "").strip(),
                    description=_strip_html(str(item.get("jobDescription") or item.get("jobExcerpt") or ""))[:5000],
                )
            )
        return results

    def fetch_rss(self, rss_url: str, limit: int = 15) -> list[RawJobPosting]:
        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(rss_url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        results: list[RawJobPosting] = []
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items[:limit]:
            title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not link:
                link_el = item.find("{http://www.w3.org/2005/Atom}link")
                if link_el is not None:
                    link = link_el.attrib.get("href", "")
            desc = item.findtext("description") or item.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            company = urlparse(rss_url).netloc or "RSS Feed"
            if title and link:
                results.append(
                    RawJobPosting(
                        source="rss",
                        title=title[:250],
                        company=company[:250],
                        location="Remote",
                        url=link[:1000],
                        description=_strip_html(desc)[:5000],
                    )
                )
        return results

    def score_fit(
        self,
        *,
        job: RawJobPosting,
        skills: list[str],
        target_roles: list[str],
        location: str,
        remote_preference: str,
        resume_text: str,
    ) -> tuple[JobFitScoreOutput, int | None]:
        """Score job fit 0-100 using Groq LLM with deterministic keyword fallback."""
        if self.groq.is_configured:
            try:
                system_prompt = load_prompt("job_discovery", "v1")
                user_prompt = (
                    f"Candidate Skills: {', '.join(skills) or 'Not listed'}\n"
                    f"Target Roles: {', '.join(target_roles) or 'Any'}\n"
                    f"Preferred Location: {location or 'Any'} | Remote Preference: {remote_preference}\n"
                    f"Resume Excerpt:\n{resume_text[:2500]}\n\n"
                    f"Job Title: {job.title}\n"
                    f"Company: {job.company}\n"
                    f"Location: {job.location}\n"
                    f"Description:\n{job.description[:3000]}"
                )
                res = self.groq.complete_json(
                    system_prompt, user_prompt, JobFitScoreOutput, temperature=0.1, max_tokens=512
                )
                return res.data, res.tokens_used
            except GroqServiceError as exc:
                logger.warning("Groq fit scoring failed, using deterministic fallback: %s", exc)

        # Deterministic overlap fallback
        haystack = f"{job.title} {job.description} {job.location}".lower()
        matched = [s for s in skills if s.lower() in haystack]
        role_bonus = 15 if any(r.lower() in job.title.lower() for r in target_roles if r) else 0
        remote_bonus = (
            10
            if remote_preference == "remote" and "remote" in f"{job.location} {job.title}".lower()
            else 0
        )
        skill_ratio = (len(matched) / max(len(skills), 1)) * 70 if skills else 45.0
        score = min(100.0, round(15.0 + skill_ratio + role_bonus + remote_bonus, 1))
        reason = (
            f"Matches {len(matched)} profile skill(s) ({', '.join(matched[:4])})"
            if matched
            else "Scored via role/location metadata (configure GROQ_API_KEY for semantic evaluation)."
        )
        return (
            JobFitScoreOutput(
                fit_score=score,
                fit_reason=reason,
                matched_skills=matched[:6],
                missing_skills=[],
            ),
            None,
        )

    def run(
        self,
        db: Session,
        user: User,
        *,
        target_roles: list[str] | None = None,
        skills: list[str] | None = None,
        location: str = "",
        remote_preference: str = "any",
        sources: list[str] | None = None,
        rss_urls: list[str] | None = None,
        query: str = "",
        limit: int = 15,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        profile = user.profile
        eff_skills = skills if skills else list((profile.skills if profile else []) or [])
        prefs = (profile.preferences if profile else {}) or {}
        eff_roles = target_roles if target_roles else list(prefs.get("target_roles", []))
        eff_sources = sources if sources else list(prefs.get("job_sources", ["himalayas", "jobicy", "remotive", "arbeitnow"]))
        eff_location = location or ", ".join(prefs.get("preferred_locations", []))
        eff_remote = remote_preference or prefs.get("remote_preference", "any")
        resume_text = (profile.master_resume_text if profile else "") or ""

        search_query = query.strip() or (eff_roles[0] if eff_roles else (eff_skills[0] if eff_skills else "software"))
        raw_jobs: list[RawJobPosting] = []
        source_errors: list[str] = []

        for src in eff_sources:
            try:
                if src == "himalayas":
                    raw_jobs.extend(self.fetch_himalayas(search_query, eff_location, limit=limit))
                elif src == "jobicy":
                    raw_jobs.extend(self.fetch_jobicy(search_query, eff_location, limit=limit))
                elif src == "remotive":
                    raw_jobs.extend(self.fetch_remotive(search_query, limit=limit))
                elif src == "arbeitnow":
                    raw_jobs.extend(self.fetch_arbeitnow(search_query, limit=limit))
            except Exception as exc:
                logger.warning("Source %s fetch failed: %s", src, exc)
                source_errors.append(f"{src}: {exc}")

        if eff_location.strip():
            loc_terms = [t.strip().lower() for t in eff_location.split(",") if t.strip()]

            def _loc_rank(p: RawJobPosting) -> int:
                loc_text = f"{p.location} {p.title}".lower()
                if any(t in loc_text for t in loc_terms):
                    return 0
                if any(g in loc_text for g in ("worldwide", "anywhere", "global", "apac")):
                    return 1
                return 2

            raw_jobs.sort(key=_loc_rank)

        for rss_url in rss_urls or []:
            try:
                raw_jobs.extend(self.fetch_rss(rss_url, limit=limit))
            except Exception as exc:
                source_errors.append(f"rss({rss_url}): {exc}")

        existing_jobs = db.scalars(select(Job).where(Job.user_id == user.id)).all()
        seen_urls = {j.url for j in existing_jobs}
        seen_keys = {_normalize_dedup_key(j.title, j.company) for j in existing_jobs}

        saved_jobs: list[Job] = []
        dedup_skipped = 0
        total_tokens = 0
        has_tokens = False

        for posting in raw_jobs:
            if not posting.url or posting.url in seen_urls:
                dedup_skipped += 1
                continue
            dedup_key = _normalize_dedup_key(posting.title, posting.company)
            if dedup_key in seen_keys:
                dedup_skipped += 1
                continue

            seen_urls.add(posting.url)
            seen_keys.add(dedup_key)

            fit, tokens = self.score_fit(
                job=posting,
                skills=eff_skills,
                target_roles=eff_roles,
                location=eff_location,
                remote_preference=eff_remote,
                resume_text=resume_text,
            )
            if tokens is not None:
                total_tokens += tokens
                has_tokens = True

            job_row = Job(
                user_id=user.id,
                source=posting.source,
                title=posting.title[:255],
                company=posting.company[:255],
                location=posting.location[:255],
                url=posting.url[:1024],
                description=posting.description,
                fit_score=fit.fit_score,
                fit_reason=fit.fit_reason,
            )
            db.add(job_row)
            saved_jobs.append(job_row)
            if len(saved_jobs) >= limit:
                break

        db.commit()
        for j in saved_jobs:
            db.refresh(j)

        saved_jobs.sort(key=lambda j: j.fit_score or 0.0, reverse=True)
        latency_ms = int((time.perf_counter() - started) * 1000)

        run_log = record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"query='{search_query}', sources={eff_sources}, limit={limit}",
            output_summary=f"saved={len(saved_jobs)}, deduplicated={dedup_skipped}",
            status="success" if not (source_errors and not saved_jobs and not raw_jobs) else "partial",
            latency_ms=latency_ms,
            tokens_used=total_tokens if has_tokens else None,
            error="; ".join(source_errors) if source_errors else None,
        )

        return {
            "discovered_count": len(saved_jobs),
            "deduplicated_count": dedup_skipped,
            "jobs": saved_jobs,
            "agent_run_id": run_log.id,
            "source_errors": source_errors,
        }

    def import_url(
        self,
        db: Session,
        user: User,
        *,
        url: str,
        title: str | None = None,
        company: str | None = None,
        location: str | None = None,
        description: str | None = None,
    ) -> Job:
        """Import a user-provided job URL respectfully (never bypassing logins/CAPTCHAs)."""
        started = time.perf_counter()
        parsed_title = (title or "").strip()
        parsed_company = (company or "").strip()
        parsed_location = (location or "").strip()
        parsed_desc = (description or "").strip()

        if not (parsed_title and parsed_desc):
            try:
                with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                if not parsed_title:
                    h1 = soup.find("h1")
                    og_title = soup.find("meta", property="og:title")
                    parsed_title = (
                        (h1.get_text(" ", strip=True) if h1 else "")
                        or (og_title.get("content", "") if og_title else "")
                        or (soup.title.string.strip() if soup.title and soup.title.string else "")
                    )
                if not parsed_company:
                    og_site = soup.find("meta", property="og:site_name")
                    parsed_company = (og_site.get("content", "") if og_site else "") or urlparse(url).netloc
                if not parsed_desc:
                    for tag in soup(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    parsed_desc = " ".join(soup.get_text(" ", strip=True).split())[:5000]
            except Exception as exc:
                if not parsed_title and not parsed_desc:
                    record_agent_run(
                        db,
                        user_id=user.id,
                        agent_name=self.name,
                        input_summary=f"import_url={url}",
                        output_summary="failed to fetch public job page",
                        status="failed",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error=str(exc),
                    )
                    raise ValueError(
                        f"Could not fetch job page ({exc}). Paste the job title and description directly to import manually."
                    ) from exc

        posting = RawJobPosting(
            source="manual_url",
            title=parsed_title or "Imported Role",
            company=parsed_company or urlparse(url).netloc or "Unknown Company",
            location=parsed_location or "Unspecified",
            url=url,
            description=parsed_desc or "No description provided.",
        )

        profile = user.profile
        prefs = (profile.preferences if profile else {}) or {}
        fit, tokens = self.score_fit(
            job=posting,
            skills=list((profile.skills if profile else []) or []),
            target_roles=list(prefs.get("target_roles", [])),
            location=", ".join(prefs.get("preferred_locations", [])),
            remote_preference=prefs.get("remote_preference", "any"),
            resume_text=(profile.master_resume_text if profile else "") or "",
        )

        job_row = Job(
            user_id=user.id,
            source=posting.source,
            title=posting.title[:255],
            company=posting.company[:255],
            location=posting.location[:255],
            url=posting.url[:1024],
            description=posting.description,
            fit_score=fit.fit_score,
            fit_reason=fit.fit_reason,
        )
        db.add(job_row)
        db.commit()
        db.refresh(job_row)

        record_agent_run(
            db,
            user_id=user.id,
            agent_name=self.name,
            input_summary=f"import_url={url}",
            output_summary=f"imported '{job_row.title}' at '{job_row.company}' (fit={fit.fit_score})",
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_used=tokens,
        )
        return job_row

    def rescore_user_jobs(
        self,
        db: Session,
        user: User,
        *,
        use_llm: bool = False,
    ) -> list[Job]:
        """Re-score all saved jobs for a user against their latest profile and master resume."""
        jobs = list(db.scalars(select(Job).where(Job.user_id == user.id)).all())
        if not jobs:
            return []

        profile = user.profile
        eff_skills = list((profile.skills if profile else []) or [])
        prefs = (profile.preferences if profile else {}) or {}
        eff_roles = list(prefs.get("target_roles", []))
        eff_location = ", ".join(prefs.get("preferred_locations", []))
        eff_remote = prefs.get("remote_preference", "any")
        resume_text = (profile.master_resume_text if profile else "") or ""

        resume_tokens = {
            tok.lower()
            for tok in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", resume_text)
            if len(tok) >= 2
        }

        for job in jobs:
            posting = RawJobPosting(
                source=job.source,
                title=job.title,
                company=job.company,
                location=job.location,
                url=job.url,
                description=job.description,
            )
            if use_llm and self.groq.is_configured:
                fit, _ = self.score_fit(
                    job=posting,
                    skills=eff_skills,
                    target_roles=eff_roles,
                    location=eff_location,
                    remote_preference=eff_remote,
                    resume_text=resume_text,
                )
                job.fit_score = fit.fit_score
                job.fit_reason = fit.fit_reason
            else:
                haystack = f"{job.title} {job.description} {job.location}".lower()
                matched_skills = [s for s in eff_skills if s.lower() in haystack]
                jd_words = {
                    w.lower()
                    for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", f"{job.title} {job.description}")
                    if len(w) >= 3
                }
                resume_overlap = len(jd_words & resume_tokens)
                role_bonus = 12 if any(r.lower() in job.title.lower() for r in eff_roles if r) else 0
                remote_bonus = (
                    8
                    if eff_remote == "remote" and "remote" in f"{job.location} {job.title}".lower()
                    else 0
                )
                skill_score = (len(matched_skills) / max(len(eff_skills), 1)) * 55.0 if eff_skills else 0.0
                resume_score = min(30.0, (resume_overlap / max(len(jd_words), 1)) * 80.0) if resume_tokens else 0.0
                score = min(100.0, round(10.0 + skill_score + resume_score + role_bonus + remote_bonus, 1))
                if matched_skills:
                    reason = f"Matches {len(matched_skills)} profile skill(s) ({', '.join(matched_skills[:5])}) and {resume_overlap} resume keyword(s)."
                elif resume_overlap > 0:
                    reason = f"Matches {resume_overlap} keyword(s) from your updated master resume."
                else:
                    reason = "Low keyword overlap with your current profile and master resume."
                job.fit_score = score
                job.fit_reason = reason
            db.add(job)

        db.commit()
        for job in jobs:
            db.refresh(job)
        jobs.sort(key=lambda j: j.fit_score or 0.0, reverse=True)
        return jobs
