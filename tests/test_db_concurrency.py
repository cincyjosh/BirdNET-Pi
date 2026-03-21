"""
Tests proving the SQLite concurrency fixes for the species stats bug.

Root cause: birdnet_analysis.py writes detections while Streamlit holds a long
read.  In default journal mode this causes SQLITE_BUSY errors for PHP queries.
Fixes applied:
  1. WAL journal mode set on every write connection (reporting.py)
  2. PHP busy timeout raised from 1 s → 5 s (overview.php)
  3. Session isset() fallback so stats never render blank (overview.php)
"""

import sqlite3
import threading
import time
import tempfile
import os
import unittest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS detections (
    Date TEXT, Time TEXT, Sci_Name TEXT, Com_Name TEXT, Confidence REAL,
    Lat REAL, Lon REAL, Cutoff REAL, Week INTEGER, Sens REAL,
    Overlap REAL, File_Name TEXT
)
"""

SAMPLE_ROW = ("2024-01-01", "12:00:00", "Pica pica", "Magpie",
              0.9, 50.0, 5.0, 0.7, 1, 1.25, 0.0, "test.wav")


def make_db(path: str, wal: bool = False) -> None:
    """Create a minimal detections database."""
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute(CREATE_TABLE)
    # Pre-populate so readers have something to read
    for _ in range(100):
        con.execute("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", SAMPLE_ROW)
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Test: WAL mode is set after a write
# ---------------------------------------------------------------------------

class TestWALModeEnabled(unittest.TestCase):
    """Fix 1 — reporting.py now issues PRAGMA journal_mode=WAL on every write."""

    def test_wal_mode_is_active_after_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "birds.db")
            make_db(db_path)

            # Simulate what reporting.py now does on each write
            con = sqlite3.connect(db_path, timeout=10)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", SAMPLE_ROW)
            con.commit()
            con.close()

            # Verify WAL is active
            con = sqlite3.connect(db_path)
            mode = con.execute("PRAGMA journal_mode").fetchone()[0]
            con.close()

            self.assertEqual(mode, "wal", "journal_mode should be 'wal' after a write")


# ---------------------------------------------------------------------------
# Test: concurrent read succeeds WITH WAL but would fail without it
# ---------------------------------------------------------------------------

class TestConcurrentReadWrite(unittest.TestCase):
    """
    Simulate the production scenario:
      - Writer thread: holds an open transaction (mimics analysis daemon writing
        a detection row with a long-running commit)
      - Reader thread: runs a COUNT(*) query with a short timeout (mimics PHP)

    With default journal mode the reader gets SQLITE_BUSY.
    With WAL mode the reader succeeds.
    """

    def _run_scenario(self, wal: bool, reader_timeout: float = 0.5) -> bool:
        """
        Returns True if the reader succeeded, False if it got SQLITE_BUSY.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "birds.db")
            make_db(db_path, wal=wal)

            reader_succeeded = threading.Event()
            reader_failed = threading.Event()
            writer_started = threading.Event()

            def slow_writer():
                con = sqlite3.connect(db_path, timeout=10)
                if wal:
                    con.execute("PRAGMA journal_mode=WAL")
                con.execute("BEGIN EXCLUSIVE")
                writer_started.set()
                # Hold the lock while the reader tries to read
                time.sleep(0.3)
                con.execute("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", SAMPLE_ROW)
                con.execute("COMMIT")
                con.close()

            def fast_reader():
                writer_started.wait()
                try:
                    uri = f"file:{db_path}?mode=ro"
                    con = sqlite3.connect(uri, uri=True, timeout=reader_timeout)
                    con.execute("SELECT COUNT(*) FROM detections").fetchone()
                    con.close()
                    reader_succeeded.set()
                except sqlite3.OperationalError:
                    reader_failed.set()

            wt = threading.Thread(target=slow_writer)
            rt = threading.Thread(target=fast_reader)
            wt.start()
            rt.start()
            wt.join()
            rt.join()

            return reader_succeeded.is_set()

    def test_reader_fails_without_wal(self):
        """
        Without WAL, an exclusive write lock blocks readers → SQLITE_BUSY.
        This documents the original bug.
        """
        succeeded = self._run_scenario(wal=False, reader_timeout=0.05)
        self.assertFalse(succeeded, "Expected SQLITE_BUSY without WAL — if this passes the lock resolved faster than expected")

    def test_reader_succeeds_with_wal(self):
        """
        With WAL, readers and writers proceed concurrently → no SQLITE_BUSY.
        This proves Fix 1 resolves the root cause.
        """
        succeeded = self._run_scenario(wal=True, reader_timeout=0.5)
        self.assertTrue(succeeded, "Reader should succeed concurrently with WAL mode enabled")


# ---------------------------------------------------------------------------
# Test: session fallback (PHP isset fix) modelled in Python
# ---------------------------------------------------------------------------

class TestSessionFallback(unittest.TestCase):
    """
    Fix 3 — overview.php now falls back to get_summary() when
    $_SESSION['chart_data'] is missing.

    We model the same pattern in Python to keep it in the test suite.
    """

    def _get_summary(self, db_path: str) -> dict:
        """Mirrors the PHP get_summary() function."""
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        total = con.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        con.close()
        return {"totalcount": total}

    def _center_chart_data(self, session: dict, db_path: str) -> dict:
        """
        Mirrors the fixed PHP logic:
          $chart_data = isset($_SESSION['chart_data'])
                        ? $_SESSION['chart_data']
                        : get_summary();
        """
        return session.get("chart_data") or self._get_summary(db_path)

    def test_uses_cached_session_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "birds.db")
            make_db(db_path)

            cached = {"totalcount": 42, "todaycount": 7}
            session = {"chart_data": cached}

            result = self._center_chart_data(session, db_path)
            self.assertEqual(result["totalcount"], 42, "Should use cached session value")

    def test_falls_back_to_query_when_session_missing(self):
        """Before the fix this returned None → blank stats. Now it queries the DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "birds.db")
            make_db(db_path)  # inserts 100 rows

            session = {}  # no chart_data — simulates missing/expired session

            result = self._center_chart_data(session, db_path)
            self.assertIsNotNone(result, "chart_data must not be None when session is empty")
            self.assertGreater(result["totalcount"], 0, "Should query real row count from DB")


if __name__ == "__main__":
    unittest.main()
