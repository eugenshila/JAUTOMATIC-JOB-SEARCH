"""Orchestration: search (fetch + score + store) and auto-apply."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .applier import Applier, ApplicationResult
from .config import Config
from .db import Store
from .matcher import Matcher
from .models import Job, SearchStats, utcnow_iso
from .net import Client
from .providers import Provider, build_providers

# When a listing has no description yet, fetch the detail page if the
# preliminary score is at least this fraction of the threshold.
PREFILTER_RATIO = 0.5


class Pipeline:
    def __init__(self, config: Config, store: Store, client: Optional[Client] = None):
        self.config = config
        self.store = store
        self.client = client or Client(config.network)
        self.providers: Dict[str, Provider] = build_providers(
            self.client, lever_apply_key=config.apply.lever_apply_key
        )
        self.matcher = Matcher(config.matching)
        self.applier = Applier(config, store, self.providers)

    # ------------------------------------------------------------------
    def search(self) -> SearchStats:
        stats = SearchStats()
        threshold = self.config.matching.threshold
        description_budget = int(self.config.network.max_description_fetches)
        blacklist = self.config.matching.company_blacklist

        for provider_name, boards in self.config.sources.items():
            provider = self.providers.get(provider_name)
            if provider is None:
                stats.errors[provider_name] = "unknown provider (skipped)"
                continue
            for board in boards:
                key = f"{provider_name}/{board}"
                try:
                    jobs = provider.fetch_jobs(board)
                except Exception as exc:
                    stats.errors[key] = str(exc)
                    continue
                stats.boards[key] = len(jobs)
                for job in jobs:
                    if any(
                        bad.strip().lower() in job.company.lower()
                        for bad in blacklist
                        if bad.strip()
                    ):
                        stats.skipped += 1
                        self.store.upsert_job(job, 0.0, ["excluded: company blacklisted"], "skipped")
                        continue

                    result = self.matcher.score(job)
                    # two-phase: fetch descriptions for promising candidates
                    if (
                        provider.supports_detail
                        and not job.description_text
                        and description_budget > 0
                        and not result.excluded
                        and result.score >= threshold * PREFILTER_RATIO
                    ):
                        try:
                            job = provider.get_job_detail(job)
                            result = self.matcher.score(job)
                            description_budget -= 1
                            stats.descriptions_fetched += 1
                        except Exception as exc:
                            # keep the preliminary score if detail fetch fails
                            result.reasons.append(f"~ could not fetch description ({exc})")

                    status = "skipped" if (result.excluded or result.score < threshold) else "matched"
                    if status == "matched":
                        stats.matched += 1
                    else:
                        stats.skipped += 1
                    row = self.store.upsert_job(job, result.score, result.reasons, status)
                    if row.get("seen_count") == 1:
                        stats.new_jobs += 1

        self.store.set_meta("last_search_at", utcnow_iso())
        return stats

    # ------------------------------------------------------------------
    def auto_apply(
        self,
        dry_run: bool = True,
        min_score: Optional[float] = None,
        max_apps: Optional[int] = None,
        force: bool = False,
    ) -> List[ApplicationResult]:
        cfg = self.config
        min_score = cfg.apply.min_score if min_score is None else float(min_score)
        max_apps = cfg.apply.max_per_run if max_apps is None else int(max_apps)
        daily_limit = int(cfg.apply.daily_limit)

        midnight_utc = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        already_today = self.store.applied_count_since(
            midnight_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        remaining_today = max(0, daily_limit - already_today)
        budget = min(max_apps, remaining_today)

        candidates = self.store.jobs(status="matched", min_score=min_score, order="score")
        results: List[ApplicationResult] = []
        submitted = 0
        for row in candidates:
            if submitted >= budget and not dry_run:
                break
            result = self.applier.apply(row, dry_run=dry_run, force=force)
            results.append(result)
            if result.status == "applied":
                submitted += 1
                if submitted < budget:
                    time.sleep(float(cfg.apply.submit_delay))
        if already_today >= daily_limit:
            # previews still happen above, but nothing more will be submitted
            results.append(
                ApplicationResult(
                    job_id=0,
                    company="",
                    title="",
                    status="failed",
                    message=(
                        f"Daily limit reached ({daily_limit} submissions today); "
                        "remaining candidates were previewed only."
                    ),
                )
            )
        return results

    # ------------------------------------------------------------------
    def apply_one(
        self, job_id: int, dry_run: bool = True, force: bool = False
    ) -> ApplicationResult:
        row = self.store.get(job_id)
        if row is None:
            raise LookupError(f"No job with id {job_id}")
        return self.applier.apply(row, dry_run=dry_run, force=force)
