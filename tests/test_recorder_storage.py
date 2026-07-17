"""Unit tests for the segment ring buffer bookkeeping and the event store."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tvd.recorder import Segment, SegmentRingBuffer
from tvd.storage import EventStore, sha256_file
from tvd.violations.base import Event


def make_seg(tmp_path, i, t0, t1):
    p = tmp_path / f"seg_{i}.mp4"
    p.write_bytes(b"x" * 16)
    return Segment(start_ts=t0, end_ts=t1, path=str(p))


def test_ring_buffer_covering_window(tmp_path):
    ring = SegmentRingBuffer(str(tmp_path), keep_seconds=1000)
    for i in range(5):
        ring.add(make_seg(tmp_path, i, i * 2.0, i * 2.0 + 2.0))
    # Window [3, 7] overlaps segments [2,4], [4,6], [6,8].
    segs = ring.segments_covering(3.0, 7.0)
    assert [(s.start_ts, s.end_ts) for s in segs] == [(2, 4), (4, 6), (6, 8)]


def test_ring_buffer_prunes_and_deletes_old_files(tmp_path):
    ring = SegmentRingBuffer(str(tmp_path), keep_seconds=5.0)
    old = make_seg(tmp_path, 0, 0.0, 2.0)
    ring.add(old)
    ring.add(make_seg(tmp_path, 1, 100.0, 102.0))  # far in the future
    assert not os.path.exists(old.path)            # pruned + removed from disk
    assert ring.segments_covering(0.0, 10.0) == []


def test_event_store_roundtrip_and_clip_update(tmp_path):
    db = tmp_path / "events.db"
    store = EventStore(str(db))
    ev = Event(type="tailgating", tier=1, confidence=0.8, ts=1700000000.0,
               meta={"time_gap_s": 0.7})
    eid = store.record(ev, speed_mps=20.0)
    rows = store.recent()
    assert len(rows) == 1 and rows[0]["type"] == "tailgating"
    assert rows[0]["clip_path"] is None

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake video bytes")
    store.update_clip(eid, str(clip))
    row = store.recent()[0]
    assert row["clip_path"] == str(clip)
    assert row["clip_sha256"] == sha256_file(str(clip))
    store.close()


def test_sha256_missing_file_is_none(tmp_path):
    assert sha256_file(str(tmp_path / "nope.mp4")) is None
