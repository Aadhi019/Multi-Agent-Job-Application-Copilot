from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.schemas.phase4 import FormFieldReportItem, FormFillReport, GeneratedAnswerItem

logger = logging.getLogger(__name__)

ARTIFACTS_ROOT = Path(__file__).resolve().parents[2] / "playwright_artifacts"


def _match_field_value(
    descriptor: str,
    tag: str,
    input_type: str,
    profile_data: dict[str, Any],
    cover_letter_text: str,
) -> tuple[str | None, str]:
    """Map an HTML field descriptor to a known profile attribute without guessing unknown fields."""
    d = descriptor.lower()
    full_name = str(profile_data.get("name", "")).strip()
    parts = full_name.split()
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    if input_type == "email" or "email" in d or "e-mail" in d:
        return profile_data.get("email") or None, "email"
    if input_type == "tel" or any(k in d for k in ("phone", "mobile", "telephone")):
        return profile_data.get("phone") or None, "phone"
    if "first" in d and "name" in d:
        return first_name or None, "first_name"
    if "last" in d and "name" in d:
        return last_name or None, "last_name"
    if any(k in d for k in ("full name", "your name", "candidate name")) or d.strip() in {"name", "full_name"}:
        return full_name or None, "name"
    if "linkedin" in d:
        return profile_data.get("linkedin_url") or None, "linkedin"
    if "github" in d:
        return profile_data.get("github_url") or None, "github"
    if any(k in d for k in ("portfolio", "website", "personal url")):
        return profile_data.get("portfolio_url") or None, "portfolio"
    if any(k in d for k in ("current company", "employer", "recent company")):
        return profile_data.get("recent_company") or None, "work_history_company"
    if any(k in d for k in ("current title", "job title", "current role")):
        return profile_data.get("recent_title") or None, "work_history_title"
    if "cover" in d and "letter" in d:
        return cover_letter_text or None, "cover_letter"
    if tag == "textarea" or any(k in d for k in ("why", "interest", "about", "summary", "experience", "project", "question")):
        return "__FREE_TEXT__", "free_text"

    return None, "unknown"


class PlaywrightFormService:
    """Headless browser form pre-filler that ALWAYS stops before final submission."""

    def __init__(self, max_retries: int = 2, timeout_ms: int = 25000) -> None:
        self.max_retries = max_retries
        self.timeout_ms = timeout_ms

    def fill_application_form(
        self,
        *,
        application_id: str,
        url: str,
        profile_data: dict[str, Any],
        resume_file_path: Path | None,
        cover_letter_text: str,
        answer_generator: Callable[[list[str]], dict[str, str]],
        headless: bool = True,
    ) -> FormFillReport:
        out_dir = ARTIFACTS_ROOT / application_id
        out_dir.mkdir(parents=True, exist_ok=True)

        last_error: str | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                return self._run_once(
                    application_id=application_id,
                    out_dir=out_dir,
                    url=url,
                    profile_data=profile_data,
                    resume_file_path=resume_file_path,
                    cover_letter_text=cover_letter_text,
                    answer_generator=answer_generator,
                    headless=headless,
                )
            except (PlaywrightTimeoutError, Exception) as exc:
                last_error = str(exc)
                logger.warning("Playwright attempt %d/%d failed for %s: %s", attempt, self.max_retries + 1, url, exc)

        return FormFillReport(
            url=url,
            status="failed",
            stopped_before_submit=True,
            notes=f"Graceful failure after {self.max_retries + 1} attempts: {last_error}",
        )

    def _run_once(
        self,
        *,
        application_id: str,
        out_dir: Path,
        url: str,
        profile_data: dict[str, Any],
        resume_file_path: Path | None,
        cover_letter_text: str,
        answer_generator: Callable[[list[str]], dict[str, str]],
        headless: bool,
    ) -> FormFillReport:
        filled: list[FormFieldReportItem] = []
        unfilled: list[FormFieldReportItem] = []
        generated_answers: list[GeneratedAnswerItem] = []
        screenshot_paths: list[str] = []
        screenshot_urls: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)

            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(400)

            # Respect site terms: never bypass CAPTCHAs or login gates
            has_captcha = (
                page.locator(
                    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha, .h-captcha, .cf-turnstile"
                ).count()
                > 0
            )
            has_password = page.locator("input[type='password']").count() > 0
            has_application_inputs = (
                page.locator("input[type='email'], input[type='file'], textarea").count() > 0
            )
            if has_captcha or (has_password and not has_application_inputs):
                blocked_path = out_dir / "blocked_gate.png"
                page.screenshot(path=str(blocked_path), full_page=True)
                browser.close()
                reason = (
                    "CAPTCHA detected; copilot stopped to respect site terms."
                    if has_captcha
                    else "Login wall detected; copilot does not bypass authentication."
                )
                return FormFillReport(
                    url=url,
                    status="blocked",
                    blocked_reason=reason,
                    screenshot_paths=[str(blocked_path)],
                    screenshot_urls=[f"/api/applications/{application_id}/screenshots/{blocked_path.name}"],
                    stopped_before_submit=True,
                    notes=reason,
                )

            before_path = out_dir / "before_fill.png"
            page.screenshot(path=str(before_path), full_page=True)
            screenshot_paths.append(str(before_path))
            screenshot_urls.append(f"/api/applications/{application_id}/screenshots/{before_path.name}")

            def _discover_controls():
                return page.evaluate(
                    """() => {
                        const els = Array.from(document.querySelectorAll('input, textarea, select'));
                        return els.map((el, idx) => {
                            const style = window.getComputedStyle(el);
                            const visible = style.display !== 'none' && style.visibility !== 'hidden' && el.type !== 'hidden';
                            let labelText = '';
                            if (el.id) {
                                const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                                if (lbl) labelText = lbl.innerText || '';
                            }
                            if (!labelText) {
                                const parentLabel = el.closest('label');
                                if (parentLabel) labelText = parentLabel.innerText || '';
                            }
                            return {
                                idx,
                                tag: el.tagName.toLowerCase(),
                                type: (el.getAttribute('type') || '').toLowerCase(),
                                name: el.getAttribute('name') || '',
                                id: el.getAttribute('id') || '',
                                placeholder: el.getAttribute('placeholder') || '',
                                ariaLabel: el.getAttribute('aria-label') || '',
                                label: labelText.trim(),
                                visible,
                            };
                        });
                    }"""
                )

            controls: list[dict[str, Any]] = _discover_controls()
            fillable_controls = [
                c
                for c in controls
                if c["visible"]
                and c["type"] not in {"submit", "button", "reset", "image", "search"}
                and "search" not in f"{c['name']} {c['id']} {c['placeholder']}".lower()
            ]

            # If this is a job-board listing page with no form inputs, follow the direct Apply link (1 hop)
            if not fillable_controls:
                apply_href = page.evaluate(
                    """() => {
                        const links = Array.from(document.querySelectorAll('a[href]'));
                        for (const a of links) {
                            const txt = (a.innerText || '').trim().toLowerCase();
                            const href = a.href || '';
                            if (!href || href.startsWith('javascript:') || /login|signin|sign-in|signup/i.test(href)) continue;
                            if (/\\bapply\\b/.test(txt)) return href;
                        }
                        return null;
                    }"""
                )
                if apply_href and apply_href != page.url:
                    page.goto(apply_href, wait_until="domcontentloaded")
                    page.wait_for_timeout(600)
                    has_captcha = (
                        page.locator(
                            "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha, .h-captcha, .cf-turnstile"
                        ).count()
                        > 0
                    )
                    if has_captcha:
                        blocked_path = out_dir / "blocked_gate.png"
                        page.screenshot(path=str(blocked_path), full_page=True)
                        browser.close()
                        reason = "CAPTCHA detected on target application form; copilot stopped to respect site terms."
                        return FormFillReport(
                            url=page.url,
                            status="blocked",
                            blocked_reason=reason,
                            screenshot_paths=[str(blocked_path)],
                            screenshot_urls=[f"/api/applications/{application_id}/screenshots/{blocked_path.name}"],
                            stopped_before_submit=True,
                            notes=reason,
                        )
                    controls = _discover_controls()
                    url = page.url

            locator_all = page.locator("input, textarea, select")
            free_text_targets: list[tuple[int, str, str]] = []

            for ctrl in controls:
                if not ctrl["visible"]:
                    continue
                tag = ctrl["tag"]
                input_type = ctrl["type"]
                if input_type in {"submit", "button", "reset", "image", "search"}:
                    continue
                if "search" in f"{ctrl['name']} {ctrl['id']} {ctrl['placeholder']}".lower():
                    continue

                field_name = ctrl["name"] or ctrl["id"] or f"field_{ctrl['idx']}"
                label = ctrl["label"] or ctrl["ariaLabel"] or ctrl["placeholder"] or field_name
                descriptor = " ".join(
                    p for p in [ctrl["label"], ctrl["ariaLabel"], ctrl["placeholder"], ctrl["name"], ctrl["id"]] if p
                )
                el_locator = locator_all.nth(ctrl["idx"])

                if input_type == "file":
                    if resume_file_path and resume_file_path.exists():
                        el_locator.set_input_files(str(resume_file_path))
                        filled.append(
                            FormFieldReportItem(
                                field_name=field_name,
                                label=label,
                                field_type="file",
                                status="uploaded",
                                value_preview=resume_file_path.name,
                            )
                        )
                    else:
                        unfilled.append(
                            FormFieldReportItem(
                                field_name=field_name,
                                label=label,
                                field_type="file",
                                status="unfilled",
                            )
                        )
                    continue

                if tag == "select":
                    unfilled.append(
                        FormFieldReportItem(
                            field_name=field_name,
                            label=label,
                            field_type="select",
                            status="unfilled",
                        )
                    )
                    continue

                if input_type in {"checkbox", "radio"}:
                    unfilled.append(
                        FormFieldReportItem(
                            field_name=field_name,
                            label=label,
                            field_type=input_type,
                            status="unfilled",
                        )
                    )
                    continue

                val, semantic_kind = _match_field_value(
                    descriptor, tag, input_type, profile_data, cover_letter_text
                )
                if val == "__FREE_TEXT__":
                    free_text_targets.append((ctrl["idx"], field_name, label))
                elif val:
                    el_locator.fill(str(val))
                    filled.append(
                        FormFieldReportItem(
                            field_name=field_name,
                            label=label,
                            field_type=semantic_kind,
                            status="filled",
                            value_preview=str(val)[:80],
                        )
                    )
                else:
                    unfilled.append(
                        FormFieldReportItem(
                            field_name=field_name,
                            label=label,
                            field_type=semantic_kind,
                            status="unfilled",
                        )
                    )

            if free_text_targets:
                questions = [lbl for _, _, lbl in free_text_targets]
                answers_map = answer_generator(questions)
                for idx, field_name, label in free_text_targets:
                    answer = answers_map.get(label, "").strip()
                    if answer:
                        locator_all.nth(idx).fill(answer)
                        filled.append(
                            FormFieldReportItem(
                                field_name=field_name,
                                label=label,
                                field_type="free_text",
                                status="filled",
                                value_preview=answer[:80],
                            )
                        )
                        generated_answers.append(GeneratedAnswerItem(question=label, answer=answer))
                    else:
                        unfilled.append(
                            FormFieldReportItem(
                                field_name=field_name,
                                label=label,
                                field_type="free_text",
                                status="unfilled",
                            )
                        )

            # STOP BEFORE SUBMIT: capture review screenshot and close browser
            review_path = out_dir / "review_step.png"
            page.screenshot(path=str(review_path), full_page=True)
            screenshot_paths.append(str(review_path))
            screenshot_urls.append(f"/api/applications/{application_id}/screenshots/{review_path.name}")
            browser.close()

        notes = (
            f"Filled {len(filled)} field(s); {len(unfilled)} left for user review. Stopped before submission."
            if (filled or unfilled)
            else "No form inputs detected on this page (it may be a job listing or JS-gated portal). Paste the direct application form URL into the Form URL box and retry."
        )

        return FormFillReport(
            url=url,
            status="ready_for_review",
            filled_fields=filled,
            unfilled_fields=unfilled,
            generated_answers=generated_answers,
            screenshot_paths=screenshot_paths,
            screenshot_urls=screenshot_urls,
            stopped_before_submit=True,
            notes=notes,
        )
