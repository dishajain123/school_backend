from __future__ import annotations

import re
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrackedApi:
    method: str
    template: str
    migration_hint: str
    track_only: bool = False


def _compile_template(template: str) -> re.Pattern:
    if template == "/api/v1/files/{}/{}":
        return re.compile(r"^/api/v1/files/[^/]+/.+$")
    pattern = re.escape(template).replace(r"\{\}", r"[^/]+")
    return re.compile(rf"^{pattern}$")


def _make_tracked(method: str, template: str, migration_hint: str, track_only: bool = False) -> TrackedApi:
    return TrackedApi(
        method=method.upper(),
        template=template,
        migration_hint=migration_hint,
        track_only=track_only,
    )


DEPRECATED_APIS: tuple[TrackedApi, ...] = (
    _make_tracked(
        "GET",
        "/api/v1/files/{}/{}",
        "Use presigned URLs returned by domain APIs (documents/gallery/receipts).",
    ),
    _make_tracked(
        "POST",
        "/api/v1/academic-years/{}/rollover",
        "Use the scheduled promotion workflow service instead.",
    ),
)


UNUSED_CANDIDATE_APIS: tuple[TrackedApi, ...] = (
    _make_tracked("GET", "/api/v1/files/{}/{}", "Used only for direct file links; confirm external consumers before deletion."),
    _make_tracked("POST", "/api/v1/academic-years/{}/rollover", "Likely infrequent yearly job; keep until observed window passes."),
)


class ApiUsageTracker:
    def __init__(
        self,
        deprecated_apis: Iterable[TrackedApi],
        unused_candidate_apis: Iterable[TrackedApi],
    ) -> None:
        self._deprecated = list(deprecated_apis)
        self._unused_candidates = list(unused_candidate_apis)
        self._deprecated_patterns = [
            (tracked, _compile_template(tracked.template))
            for tracked in self._deprecated
        ]
        self._unused_patterns = [
            (tracked, _compile_template(tracked.template))
            for tracked in self._unused_candidates
        ]
        self._deprecated_hits: dict[tuple[str, str], int] = {}
        self._unused_hits: dict[tuple[str, str], int] = {}
        self._endpoint_stats: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"hits": 0, "errors": 0}
        )

    @staticmethod
    def _key(method: str, template: str) -> tuple[str, str]:
        return method.upper(), template

    def _match(self, method: str, path: str, patterns: list[tuple[TrackedApi, re.Pattern]]) -> Optional[TrackedApi]:
        method = method.upper()
        for tracked, regex in patterns:
            if tracked.method != method:
                continue
            if regex.match(path):
                return tracked
        return None

    def match_deprecated(self, method: str, path: str) -> Optional[TrackedApi]:
        return self._match(method, path, self._deprecated_patterns)

    def match_unused_candidate(self, method: str, path: str) -> Optional[TrackedApi]:
        return self._match(method, path, self._unused_patterns)

    def record_deprecated_hit(self, tracked: TrackedApi) -> int:
        key = self._key(tracked.method, tracked.template)
        self._deprecated_hits[key] = self._deprecated_hits.get(key, 0) + 1
        return self._deprecated_hits[key]

    def record_unused_candidate_hit(self, tracked: TrackedApi) -> int:
        key = self._key(tracked.method, tracked.template)
        self._unused_hits[key] = self._unused_hits.get(key, 0) + 1
        return self._unused_hits[key]

    @staticmethod
    def _normalize_path(path: str) -> str:
        # Collapse UUID-ish and numeric path segments so metrics aggregate well.
        segments = []
        uuid_like = re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        )
        for seg in path.split("/"):
            if not seg:
                continue
            if seg.isdigit() or uuid_like.match(seg):
                segments.append("{}")
            else:
                segments.append(seg)
        return "/" + "/".join(segments)

    def record_request(self, *, method: str, path: str, status_code: int) -> None:
        key = (method.upper(), self._normalize_path(path))
        self._endpoint_stats[key]["hits"] += 1
        if status_code >= 400:
            self._endpoint_stats[key]["errors"] += 1

    def get_unused_candidate_statuses(self) -> list[dict[str, str | int]]:
        rows: list[dict[str, str | int]] = []
        for tracked in self._unused_candidates:
            key = self._key(tracked.method, tracked.template)
            hits = self._unused_hits.get(key, 0)
            actively_used = hits > 0
            if actively_used:
                status = "actively used"
                confidence = "Low"
            else:
                status = "confirmed unused"
                confidence = "Medium"

            rows.append(
                {
                    "method": tracked.method,
                    "template": tracked.template,
                    "hits": hits,
                    "status": status,
                    "confidence": confidence,
                    "phase_1": "Deprecate + announce migration path",
                    "phase_2": "Monitor usage logs for one release cycle",
                    "phase_3": "Delete endpoint and remove route/service code",
                    "migration_hint": tracked.migration_hint,
                }
            )
        return rows

    def get_endpoint_metrics(self) -> list[dict[str, str | int | float]]:
        rows: list[dict[str, str | int | float]] = []
        for (method, endpoint), stats in self._endpoint_stats.items():
            hits = stats["hits"]
            errors = stats["errors"]
            error_rate = round((errors / hits) * 100, 2) if hits else 0.0
            rows.append(
                {
                    "method": method,
                    "endpoint": endpoint,
                    "hits": hits,
                    "errors": errors,
                    "error_rate": error_rate,
                }
            )
        rows.sort(key=lambda x: (-int(x["hits"]), str(x["method"]), str(x["endpoint"])))
        return rows

    def log_runtime_summary(self) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        logger.info("API usage runtime summary generated at %s", timestamp)
        for row in self.get_unused_candidate_statuses():
            logger.info(
                "unused_candidate method=%s template=%s hits=%s status=%s confidence=%s phase1=%s phase2=%s phase3=%s",
                row["method"],
                row["template"],
                row["hits"],
                row["status"],
                row["confidence"],
                row["phase_1"],
                row["phase_2"],
                row["phase_3"],
            )
        metrics = self.get_endpoint_metrics()
        if not metrics:
            logger.info("api_usage_metrics no traffic observed in current runtime window")
            return

        most_used = metrics[:10]
        least_used = sorted(metrics, key=lambda x: (int(x["hits"]), str(x["endpoint"])))[:10]
        logger.info("api_usage_metrics most_used_count=%s least_used_count=%s", len(most_used), len(least_used))

        for row in most_used:
            logger.info(
                "api_usage_most_used method=%s endpoint=%s hits=%s errors=%s error_rate_pct=%s",
                row["method"],
                row["endpoint"],
                row["hits"],
                row["errors"],
                row["error_rate"],
            )
        for row in least_used:
            logger.info(
                "api_usage_least_used method=%s endpoint=%s hits=%s errors=%s error_rate_pct=%s",
                row["method"],
                row["endpoint"],
                row["hits"],
                row["errors"],
                row["error_rate"],
            )


api_usage_tracker = ApiUsageTracker(
    deprecated_apis=DEPRECATED_APIS,
    unused_candidate_apis=UNUSED_CANDIDATE_APIS,
)
