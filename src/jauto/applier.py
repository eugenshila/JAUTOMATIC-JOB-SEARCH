"""Build and (optionally) submit applications.

Safety model:
- Every application is *previewed* by default; submission requires an explicit
  --yes or apply.auto_submit: true.
- Required questions that cannot be answered from the profile/config mark the
  application 'needs_review' instead of being guessed.
- POST submissions are never retried, and real submissions are spaced by
  apply.submit_delay and capped by apply.daily_limit.
"""

from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .db import Store
from .models import Job, normalize
from .providers import Provider, Question, T_FILE, T_MULTI, T_SINGLE, T_TEXT, T_TEXTAREA


@dataclass
class BuiltApplication:
    job: Job
    provider: str
    endpoint: str
    form: Dict[str, Any] = field(default_factory=dict)
    files: List[Tuple[str, str, bytes]] = field(default_factory=list)  # (field, filename, content)
    missing_required: List[str] = field(default_factory=list)
    unmapped_optional: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.missing_required

    def payload_summary(self) -> Dict[str, Any]:
        """What gets logged to the applications table (files summarised)."""
        return {
            "form": self.form,
            "files": [
                {"field": f, "filename": n, "bytes": len(c)} for f, n, c in self.files
            ],
        }


@dataclass
class ApplicationResult:
    job_id: int
    company: str
    title: str
    status: str  # applied | dry_run | needs_review | failed | manual
    message: str = ""
    built: Optional[BuiltApplication] = None
    apply_url: str = ""


class Applier:
    def __init__(self, config: Config, store: Store, providers: Dict[str, Provider]):
        self.config = config
        self.store = store
        self.providers = providers

    # ------------------------------------------------------------------
    def build(self, job: Job, spec, endpoint: str) -> BuiltApplication:
        cfg = self.config
        profile = cfg.profile
        apply_cfg = cfg.apply

        built = BuiltApplication(job=job, provider=job.provider, endpoint=endpoint)
        resume_done = False

        for question in spec.questions:
            name = question.name
            label = question.label or name
            lname = label.lower()

            # --- resume / cover letter need file handling ----------------
            if name == "resume" and question.type == T_FILE:
                self._attach_resume(built)
                resume_done = True
                continue
            if name == "resume_text" and question.type == T_TEXTAREA:
                if not resume_done and not self._attach_resume(built):
                    text_path = cfg.resolve_path(profile.resume_text_path)
                    if text_path and os.path.isfile(text_path):
                        with open(text_path, "r", encoding="utf-8", errors="replace") as fh:
                            built.form[name] = fh.read()
                    elif question.required:
                        built.missing_required.append(f"{label} (no resume configured)")
                continue
            if name == "cover_letter" and question.type == T_FILE:
                self._attach_cover_letter(built)
                continue
            if name == "cover_letter_text" and question.type == T_TEXTAREA:
                text = self._render_cover_letter(job)
                if text:
                    built.form[name] = text
                elif question.required:
                    built.missing_required.append(f"{label} (no cover letter configured)")
                continue

            # --- standard identity fields --------------------------------
            value = self._standard_field(name)
            if value is None:
                value = self._answer_for_label(label)
            if value is None:
                value = self._link_for_label(lname)
            if value is None and question.kind == "eeo":
                value = self._eeo_for_label(lname)
            if value is None:
                if question.required:
                    built.missing_required.append(
                        self._describe_unmapped(question, value)
                    )
                else:
                    built.unmapped_optional.append(label)
                continue

            # --- option mapping for selects ------------------------------
            if question.type in (T_SINGLE, T_MULTI) and question.options:
                mapped = self._map_options(question, value)
                if mapped is None:
                    if question.required:
                        built.missing_required.append(
                            f"{label}: answer {value!r} does not match any option "
                            f"({', '.join(lbl for _, lbl in question.options)})"
                        )
                    else:
                        built.unmapped_optional.append(label)
                    continue
                value = mapped

            built.form[name] = value

        # --- GDPR consent ----------------------------------------------
        if spec.requires_gdpr_consent:
            if apply_cfg.consent_gdpr:
                built.form["data_compliance[gdpr_consent_given]"] = "1"
                built.form["data_compliance[gdpr_processing_consent_given]"] = "1"
                built.form["data_compliance[gdpr_retention_consent_given]"] = "1"
            else:
                built.missing_required.append(
                    "GDPR consent is required by this employer; set apply.consent_gdpr: "
                    "true to auto-consent (only do this if you actually consent)"
                )
        built.warnings.extend(spec.notes or [])
        has_resume = bool(
            built.form.get("resume_text") or any(f == "resume" for f, _, _ in built.files)
        )
        spec_asks_for_resume = any(q.name in ("resume", "resume_text") for q in spec.questions)
        if cfg.apply.require_resume and spec_asks_for_resume and not has_resume:
            built.missing_required.append("Resume (none attached)")
        elif not spec_asks_for_resume:
            built.warnings.append("this form does not ask for a resume")
        return built

    # ------------------------------------------------------------------
    def apply(
        self,
        job_row: Dict[str, Any],
        dry_run: bool = True,
        force: bool = False,
    ) -> ApplicationResult:
        job = Job.from_row(job_row)
        provider = self.providers.get(job.provider)

        if provider is None or not provider.apply_supported:
            return ApplicationResult(
                job_id=job_row["id"],
                company=job_row["company"],
                title=job_row["title"],
                status="manual",
                message=(
                    f"{job.provider} applications are not automated yet — "
                    f"apply manually: {job_row.get('apply_url') or job_row.get('url')}"
                ),
                apply_url=job_row.get("apply_url") or job_row.get("url") or "",
            )

        try:
            spec = provider.get_application_spec(job)
        except Exception as exc:  # API / network error — treat as failure, not crash
            return ApplicationResult(
                job_id=job_row["id"],
                company=job_row["company"],
                title=job_row["title"],
                status="failed",
                message=f"Could not load application form: {exc}",
            )
        if spec is None or not spec.questions:
            return ApplicationResult(
                job_id=job_row["id"],
                company=job_row["company"],
                title=job_row["title"],
                status="manual",
                message=(
                    "This board does not expose an application form through the API — "
                    f"apply manually: {job_row.get('apply_url') or job_row.get('url')}"
                ),
                apply_url=job_row.get("apply_url") or job_row.get("url") or "",
            )

        built = self.build(job, spec, endpoint=job.provider)
        result = ApplicationResult(
            job_id=job_row["id"],
            company=job_row["company"],
            title=job_row["title"],
            status="dry_run",
            built=built,
            apply_url=job_row.get("apply_url") or "",
        )

        if built.missing_required and not force:
            result.status = "needs_review"
            result.message = "Unanswered required questions:\n  - " + "\n  - ".join(
                built.missing_required
            )
            self.store.set_status(job_row["id"], "needs_review")
            return result

        if dry_run:
            self.store.record_application(
                job_row["id"], "dry", built.endpoint, built.payload_summary(), True, None, "dry run"
            )
            return result

        try:
            ok, http_status, response = provider.submit_application(
                job, built.form, built.files
            )
        except Exception as exc:
            ok, http_status, response = False, None, f"submission error: {exc}"
        self.store.record_application(
            job_row["id"], "auto", built.endpoint, built.payload_summary(),
            ok, http_status, response,
        )
        if ok:
            result.status = "applied"
            self.store.set_status(job_row["id"], "applied")
        else:
            result.status = "failed"
            self.store.set_status(job_row["id"], "failed")
            result.message = f"Submission rejected (HTTP {http_status}): {response}"
        return result

    # ------------------------------------------------------------------
    # answer resolution helpers
    # ------------------------------------------------------------------
    def _standard_field(self, name: str) -> Optional[str]:
        profile = self.config.profile
        mapping = {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "preferred_name": profile.preferred_name or profile.first_name,
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
        }
        return mapping.get(name) or None

    def _answer_for_label(self, label: str) -> Optional[str]:
        answers = self.config.apply.answers or {}
        norm = normalize(label)
        for key, value in answers.items():
            k = normalize(key)
            if k == norm or k in norm or norm in k:
                return str(value)
        return None

    def _link_for_label(self, lower_label: str) -> Optional[str]:
        links = self.config.profile.links or {}
        for key, url in links.items():
            if key and key in lower_label:
                return url
        if "portfolio" in lower_label or "website" in lower_label or "blog" in lower_label:
            return links.get("portfolio")
        return None

    def _eeo_for_label(self, lower_label: str) -> Optional[str]:
        eeo = self.config.apply.eeo_answers or {}
        for key, value in eeo.items():
            if key and key in lower_label:
                return str(value)
        return None

    @staticmethod
    def _describe_unmapped(question: Question, value) -> str:
        label = question.label or question.name
        detail = ""
        if question.options:
            detail = f" — options: {', '.join(lbl for _, lbl in question.options if lbl)}"
        return f"{label}{detail}"

    @staticmethod
    def _map_options(question: Question, answer: Any):
        """Map a human answer to option value(s); None if nothing matches."""
        if question.type == T_MULTI:
            wanted = [normalize(p) for p in str(answer).split(",")]
            values = []
            for value, opt_label in question.options:
                if any(w == normalize(opt_label or "") or w in normalize(opt_label or "") for w in wanted):
                    values.append(value)
            return values or None
        norm = normalize(str(answer))
        for value, opt_label in question.options:
            if norm == normalize(opt_label or "") or norm in normalize(opt_label or ""):
                return value
        return None

    # ------------------------------------------------------------------
    # attachments
    # ------------------------------------------------------------------
    def _attach_resume(self, built: BuiltApplication) -> bool:
        path = self.config.resume_file
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                content = fh.read()
            built.files.append(("resume", os.path.basename(path), content))
            return True
        text_path = self.config.resolve_path(self.config.profile.resume_text_path)
        if text_path and os.path.isfile(text_path):
            with open(text_path, "r", encoding="utf-8", errors="replace") as fh:
                built.form["resume_text"] = fh.read()
            return True
        return False

    def _attach_cover_letter(self, built: BuiltApplication) -> bool:
        path = self.config.resolve_path(self.config.profile.cover_letter_path)
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                content = fh.read()
            built.files.append(("cover_letter", os.path.basename(path), content))
            return True
        text = self._render_cover_letter(built.job)
        if text:
            built.form["cover_letter_text"] = text
            return True
        return False

    def _render_cover_letter(self, job: Job) -> str:
        template_path = self.config.resolve_path(
            self.config.profile.cover_letter_template
        )
        if not template_path or not os.path.isfile(template_path):
            return ""
        with open(template_path, "r", encoding="utf-8") as fh:
            template = fh.read()
        values = {
            "name": self.config.profile.full_name,
            "first_name": self.config.profile.first_name,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "skills": ", ".join(self.config.matching.skills[:6]),
        }

        class _SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"

        try:
            return string.Formatter().vformat(template, (), _SafeDict(values))
        except Exception:
            return template
