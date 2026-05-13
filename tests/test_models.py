"""Tests for api/models.py using real response shapes from docs/api-notes.md."""
from datetime import datetime, timezone

import pytest

from cc_usage.api.models import Bucket, UsageSnapshot


def _make_snapshot(buckets=None, extra_usage_enabled=False, fetched_at=None):
    return UsageSnapshot(
        buckets=buckets or {},
        extra_usage_enabled=extra_usage_enabled,
        fetched_at=fetched_at or datetime.now(tz=timezone.utc),
    )


class TestBucketFromJson:
    def test_null_returns_none(self):
        assert Bucket.from_json(None) is None

    def test_full_bucket(self):
        d = {"utilization": 42.5, "resets_at": "2026-05-09T08:20:39+00:00"}
        bucket = Bucket.from_json(d)
        assert bucket is not None
        assert bucket.utilization == 42.5
        assert bucket.resets_at is not None
        assert bucket.resets_at.tzinfo is not None

    def test_missing_resets_at(self):
        d = {"utilization": 10.0}
        bucket = Bucket.from_json(d)
        assert bucket is not None
        assert bucket.resets_at is None

    def test_null_resets_at(self):
        d = {"utilization": 0.0, "resets_at": None}
        bucket = Bucket.from_json(d)
        assert bucket is not None
        assert bucket.resets_at is None

    def test_utilization_is_percentage(self):
        # Field is 0..100, not a fraction
        d = {"utilization": 87.3, "resets_at": None}
        bucket = Bucket.from_json(d)
        assert bucket.utilization == pytest.approx(87.3)


class TestUsageSnapshotNamedBuckets:
    def test_all_none_returns_empty(self):
        snap = _make_snapshot()
        assert snap.named_buckets() == []

    def test_display_order(self):
        five = Bucket(utilization=10.0, resets_at=None)
        seven = Bucket(utilization=20.0, resets_at=None)
        opus = Bucket(utilization=5.0, resets_at=None)
        snap = _make_snapshot(buckets={"five_hour": five, "seven_day": seven, "seven_day_opus": opus})
        labels = [label for label, _ in snap.named_buckets()]
        assert labels == ["5h", "7d", "7d Opus"]

    def test_only_non_null_included(self):
        seven = Bucket(utilization=50.0, resets_at=None)
        snap = _make_snapshot(buckets={"seven_day": seven})
        assert len(snap.named_buckets()) == 1
        assert snap.named_buckets()[0][0] == "7d"


class TestUsageSnapshotUnknownBucket:
    def test_unknown_bucket_appears_with_humanized_label(self):
        # The API may add bucket keys we don't know about. They should still
        # show up rather than be silently dropped.
        snap = _make_snapshot(buckets={
            "seven_day": Bucket(utilization=10.0, resets_at=None),
            "seven_day_brand_new_thing": Bucket(utilization=20.0, resets_at=None),
        })
        labels = [label for label, _ in snap.named_buckets()]
        assert labels == ["7d", "7d Brand New Thing"]


class TestUsageSnapshotMaxUtilization:
    def test_all_none_returns_zero(self):
        snap = _make_snapshot()
        assert snap.max_utilization() == 0.0

    def test_single_bucket(self):
        snap = _make_snapshot(buckets={"five_hour": Bucket(utilization=63.2, resets_at=None)})
        assert snap.max_utilization() == pytest.approx(63.2)

    def test_picks_highest(self):
        snap = _make_snapshot(buckets={
            "five_hour": Bucket(utilization=30.0, resets_at=None),
            "seven_day": Bucket(utilization=85.0, resets_at=None),
            "seven_day_opus": Bucket(utilization=10.0, resets_at=None),
        })
        assert snap.max_utilization() == pytest.approx(85.0)

    def test_real_api_shape(self):
        # Representative response from docs/api-notes.md
        five = Bucket.from_json({"utilization": 0.0, "resets_at": "2026-05-08T12:00:00+00:00"})
        seven = Bucket.from_json({"utilization": 14.28, "resets_at": "2026-05-15T00:00:00+00:00"})
        snap = _make_snapshot(buckets={"five_hour": five, "seven_day": seven})
        assert snap.max_utilization() == pytest.approx(14.28)
