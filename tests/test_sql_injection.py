"""
Tests proving that parameterized queries prevent SQL injection.

These tests exercise SQLite's parameterization behavior directly in Python,
mirroring the PHP SQLite3 bindValue() pattern used in the fixes to
common.php, history.php, and todays_detections.php.

They prove two things:
  1. Without parameterization, injection payloads manipulate query results.
  2. With parameterization (the fix), the same payloads are treated as
     literal values and return no rows.
"""

import sqlite3
import tempfile
import os
import unittest


CREATE_TABLE = """
CREATE TABLE detections (
    Date TEXT, Time TEXT, Sci_Name TEXT, Com_Name TEXT, Confidence REAL,
    Lat REAL, Lon REAL, Cutoff REAL, Week INTEGER, Sens REAL,
    Overlap REAL, File_Name TEXT
)
"""


def make_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute(CREATE_TABLE)
    con.executemany("INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("2024-01-01", "08:00:00", "Pica pica",       "Magpie",       0.92, 50, 5, 0.7, 1, 1.25, 0.0, "a.wav"),
        ("2024-01-01", "09:00:00", "Turdus merula",   "Blackbird",    0.88, 50, 5, 0.7, 1, 1.25, 0.0, "b.wav"),
        ("2024-01-02", "10:00:00", "Erithacus rubecula", "Robin",     0.95, 50, 5, 0.7, 1, 1.25, 0.0, "c.wav"),
    ])
    con.commit()
    return con


# ---------------------------------------------------------------------------
# Helpers mirroring the PHP query patterns
# ---------------------------------------------------------------------------

def fetch_species_array_unsafe(con, date=None):
    """Original vulnerable PHP pattern — string interpolation."""
    where = f'WHERE Date == "{date}"' if date else ""
    return con.execute(
        f"SELECT Com_Name FROM detections {where} GROUP BY Sci_Name"
    ).fetchall()


def fetch_species_array_safe(con, date=None):
    """Fixed PHP pattern — named parameter.
    Note: Python sqlite3 uses {"date": val}, PHP SQLite3 uses {":date": val} —
    different dict key convention but same underlying SQLite behaviour."""
    if date:
        return con.execute(
            "SELECT Com_Name FROM detections WHERE Date = :date GROUP BY Sci_Name",
            {"date": date}
        ).fetchall()
    return con.execute(
        "SELECT Com_Name FROM detections GROUP BY Sci_Name"
    ).fetchall()


def fetch_best_detection_unsafe(con, com_name):
    """Original vulnerable PHP pattern."""
    return con.execute(
        f'SELECT Com_Name FROM detections WHERE Com_Name = "{com_name}"'
    ).fetchall()


def fetch_best_detection_safe(con, com_name):
    """Fixed PHP pattern."""
    return con.execute(
        "SELECT Com_Name FROM detections WHERE Com_Name = :com_name",
        {"com_name": com_name}
    ).fetchall()


def search_detections_unsafe(con, searchterm):
    """Original vulnerable todays_detections.php LIKE pattern."""
    return con.execute(
        f"SELECT Com_Name FROM detections WHERE Com_Name LIKE '%{searchterm}%'"
    ).fetchall()


def search_detections_safe(con, searchterm):
    """Fixed pattern — positional parameter."""
    return con.execute(
        "SELECT Com_Name FROM detections WHERE Com_Name LIKE ?",
        (f"%{searchterm}%",)
    ).fetchall()


# ---------------------------------------------------------------------------
# Tests: fetch_species_array ($date injection)
# ---------------------------------------------------------------------------

class TestFetchSpeciesArrayInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.con = make_db(os.path.join(self.tmpdir.name, "birds.db"))

    def tearDown(self):
        self.con.close()
        self.tmpdir.cleanup()

    def test_normal_query_returns_correct_rows(self):
        rows = fetch_species_array_safe(self.con, "2024-01-01")
        names = [r[0] for r in rows]
        self.assertIn("Magpie", names)
        self.assertIn("Blackbird", names)
        self.assertNotIn("Robin", names)  # Robin is on 2024-01-02

    def test_injection_works_without_parameterization(self):
        """
        Documents the original bug: injecting OR 1=1 returns all rows
        regardless of date filter.
        """
        payload = '2024-01-01" OR "1"="1'
        rows = fetch_species_array_unsafe(self.con, payload)
        names = [r[0] for r in rows]
        # Injection bypasses the date filter — all 3 species returned
        self.assertIn("Robin", names, "Injection should bypass date filter (documents the bug)")

    def test_injection_blocked_with_parameterization(self):
        """
        Proves the fix: the same payload is treated as a literal string
        and matches no rows.
        """
        payload = '2024-01-01" OR "1"="1'
        rows = fetch_species_array_safe(self.con, payload)
        self.assertEqual(rows, [], "Injection payload should match no rows with parameterization")


# ---------------------------------------------------------------------------
# Tests: fetch_best_detection ($com_name injection)
# ---------------------------------------------------------------------------

class TestFetchBestDetectionInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.con = make_db(os.path.join(self.tmpdir.name, "birds.db"))

    def tearDown(self):
        self.con.close()
        self.tmpdir.cleanup()

    def test_normal_query_returns_correct_row(self):
        rows = fetch_best_detection_safe(self.con, "Magpie")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Magpie")

    def test_injection_works_without_parameterization(self):
        payload = '" OR "1"="1'
        rows = fetch_best_detection_unsafe(self.con, payload)
        # Returns all rows — injection bypasses the filter
        self.assertGreater(len(rows), 1, "Injection should return all rows (documents the bug)")

    def test_injection_blocked_with_parameterization(self):
        payload = '" OR "1"="1'
        rows = fetch_best_detection_safe(self.con, payload)
        self.assertEqual(rows, [], "Injection payload should match no rows with parameterization")


# ---------------------------------------------------------------------------
# Tests: searchterm LIKE injection (todays_detections.php)
# ---------------------------------------------------------------------------

class TestSearchTermInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.con = make_db(os.path.join(self.tmpdir.name, "birds.db"))

    def tearDown(self):
        self.con.close()
        self.tmpdir.cleanup()

    def test_normal_search_returns_matching_rows(self):
        rows = search_detections_safe(self.con, "Magpie")
        self.assertEqual(len(rows), 1)

    def test_injection_works_without_parameterization(self):
        """
        LIKE injection: closing the LIKE and appending OR 1=1 returns all rows.
        """
        payload = "%' OR '1'='1"
        rows = search_detections_unsafe(self.con, payload)
        self.assertGreater(len(rows), 1, "LIKE injection should return all rows (documents the bug)")

    def test_injection_blocked_with_parameterization(self):
        payload = "%' OR '1'='1"
        rows = search_detections_safe(self.con, payload)
        self.assertEqual(rows, [], "LIKE injection payload should match no rows with parameterization")

    def test_legitimate_search_still_works_after_fix(self):
        # "Blackbird" contains "bird" — expect 1 result
        rows = search_detections_safe(self.con, "bird")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Blackbird")
        # Prefix match
        rows = search_detections_safe(self.con, "Mag")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Magpie")
        # No match
        rows = search_detections_safe(self.con, "Sparrow")
        self.assertEqual(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
