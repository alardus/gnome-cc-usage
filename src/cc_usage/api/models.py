from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar


@dataclass(frozen=True)
class Bucket:
    utilization: float      # 0..100 (already a percentage, not a fraction)
    resets_at: datetime | None

    @staticmethod
    def from_json(d: dict | None) -> "Bucket | None":
        if d is None:
            return None
        raw = d.get("resets_at")
        resets_at = datetime.fromisoformat(raw) if raw else None
        return Bucket(utilization=float(d["utilization"]), resets_at=resets_at)


@dataclass(frozen=True)
class UsageSnapshot:
    buckets: dict[str, Bucket]      # only non-null entries, keyed by API field name
    extra_usage_enabled: bool
    fetched_at: datetime

    # Preferred display order + friendly label for known buckets. Unknown
    # keys not in this map are appended in dict-iteration order with a
    # humanized fallback label (see _label_for).
    _LABELS: ClassVar[dict[str, str]] = {
        "five_hour": "5h",
        "seven_day": "7d",
        "seven_day_opus": "7d Opus",
        "seven_day_sonnet": "7d Sonnet",
    }
    _ORDER: ClassVar[tuple[str, ...]] = (
        "five_hour",
        "seven_day",
        "seven_day_opus",
        "seven_day_sonnet",
    )

    @staticmethod
    def _label_for(key: str) -> str:
        if key in UsageSnapshot._LABELS:
            return UsageSnapshot._LABELS[key]
        parts = key.split("_")
        if len(parts) >= 2 and parts[0] == "seven" and parts[1] == "day":
            tail = " ".join(p.capitalize() for p in parts[2:])
            return f"7d {tail}".strip()
        if len(parts) >= 2 and parts[0] == "five" and parts[1] == "hour":
            tail = " ".join(p.capitalize() for p in parts[2:])
            return f"5h {tail}".strip()
        return " ".join(p.capitalize() for p in parts)

    def named_buckets(self) -> list[tuple[str, Bucket]]:
        result: list[tuple[str, Bucket]] = []
        seen: set[str] = set()
        for key in self._ORDER:
            if key in self.buckets:
                result.append((self._label_for(key), self.buckets[key]))
                seen.add(key)
        for key, bucket in self.buckets.items():
            if key not in seen:
                result.append((self._label_for(key), bucket))
        return result

    def max_utilization(self) -> float:
        if not self.buckets:
            return 0.0
        return max(b.utilization for b in self.buckets.values())


@dataclass(frozen=True)
class ApiError(Exception):
    status: int
    message: str
    is_rate_limit: bool     # True if status == 429
    is_auth_error: bool     # True if status in (401, 403)
    retry_after: int | None = None    # seconds; from Retry-After header on 429
