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
        f"SELECT Com_Name FROM detections {where} GROUP BY Sci_Name"  # nosec B608 - intentional: documents the vulnerable pattern
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
        f'SELECT Com_Name FROM detections WHERE Com_Name = "{com_name}"'  # nosec B608 - intentional: documents the vulnerable pattern
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
        f"SELECT Com_Name FROM detections WHERE Com_Name LIKE '%{searchterm}%'"  # nosec B608 - intentional: documents the vulnerable pattern
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


# ---------------------------------------------------------------------------
# Tests: play.php filename injection ($name interpolated in prepare())
# ---------------------------------------------------------------------------

def fetch_by_filename_unsafe(con, filename):
    """Mirrors play.php line 640: prepare() with interpolated $name — still injectable."""
    return con.execute(
        f'SELECT * FROM detections WHERE File_Name == "{filename}" ORDER BY Date DESC, Time DESC'  # nosec B608 - intentional: documents the vulnerable pattern
    ).fetchall()


def fetch_by_filename_safe(con, filename):
    """Fixed pattern — bindValue equivalent: positional parameter."""
    return con.execute(
        "SELECT * FROM detections WHERE File_Name = ? ORDER BY Date DESC, Time DESC",
        (filename,)
    ).fetchall()


class TestPlayPhpFilenameInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.con = make_db(os.path.join(self.tmpdir.name, "birds.db"))

    def tearDown(self):
        self.con.close()
        self.tmpdir.cleanup()

    def test_normal_query_returns_correct_row(self):
        rows = fetch_by_filename_safe(self.con, "a.wav")
        self.assertEqual(len(rows), 1)

    def test_injection_works_without_parameterization(self):
        """Documents the bug: GET ?filename=<payload> bypasses File_Name filter."""
        payload = '" OR "1"="1'
        rows = fetch_by_filename_unsafe(self.con, payload)
        self.assertGreater(len(rows), 1, "Injection should return all rows (documents the bug)")

    def test_injection_blocked_with_parameterization(self):
        payload = '" OR "1"="1'
        rows = fetch_by_filename_safe(self.con, payload)
        self.assertEqual(rows, [], "Injection payload should match no rows with parameterization")


# ---------------------------------------------------------------------------
# Tests: db.py get_todays_count_for / get_this_weeks_count_for sci_name injection
# ---------------------------------------------------------------------------

def get_todays_count_unsafe(con, sci_name):
    """Mirrors db.py get_todays_count_for — f-string interpolation."""
    today = "2024-01-01"
    # nosec B608 - intentional: documents the vulnerable pattern
    select_sql = f"SELECT COUNT(*) FROM detections WHERE Date = DATE('{today}') AND Sci_Name = '{sci_name}'"
    return con.execute(select_sql).fetchone()[0]


def get_todays_count_safe(con, sci_name):
    """Fixed — parameterized."""
    today = "2024-01-01"
    row = con.execute(
        "SELECT COUNT(*) FROM detections WHERE Date = DATE(?) AND Sci_Name = ?",
        (today, sci_name)
    ).fetchone()
    return row[0] if row else 0


def get_species_by_date_unsafe(con, date):
    """Mirrors db.py get_species_by — f-string date interpolation."""
    where = f'WHERE Date == "{date}"'
    return con.execute(
        f"SELECT Com_Name FROM detections {where} GROUP BY Sci_Name"  # nosec B608 - intentional: documents the vulnerable pattern
    ).fetchall()


def get_species_by_date_safe(con, date):
    """Fixed — parameterized."""
    return con.execute(
        "SELECT Com_Name FROM detections WHERE Date = ? GROUP BY Sci_Name",
        (date,)
    ).fetchall()


class TestDbPySciNameInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.con = make_db(os.path.join(self.tmpdir.name, "birds.db"))

    def tearDown(self):
        self.con.close()
        self.tmpdir.cleanup()

    def test_normal_count_returns_correct_value(self):
        count = get_todays_count_safe(self.con, "Pica pica")
        self.assertEqual(count, 1)

    def test_sci_name_injection_works_without_parameterization(self):
        """Documents the bug: injecting OR 1=1 inflates the count."""
        payload = "Pica pica' OR '1'='1"
        count = get_todays_count_unsafe(self.con, payload)
        self.assertGreater(count, 1, "Injection should inflate count (documents the bug)")

    def test_sci_name_injection_blocked_with_parameterization(self):
        payload = "Pica pica' OR '1'='1"
        count = get_todays_count_safe(self.con, payload)
        self.assertEqual(count, 0, "Injection payload should return zero matches")


class TestDbPyGetSpeciesByDateInjection(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.con = make_db(os.path.join(self.tmpdir.name, "birds.db"))

    def tearDown(self):
        self.con.close()
        self.tmpdir.cleanup()

    def test_normal_date_filter_works(self):
        rows = get_species_by_date_safe(self.con, "2024-01-01")
        names = [r[0] for r in rows]
        self.assertIn("Magpie", names)
        self.assertNotIn("Robin", names)

    def test_date_injection_works_without_parameterization(self):
        payload = '2024-01-01" OR "1"="1'
        rows = get_species_by_date_unsafe(self.con, payload)
        names = [r[0] for r in rows]
        self.assertIn("Robin", names, "Injection should bypass date filter (documents the bug)")

    def test_date_injection_blocked_with_parameterization(self):
        payload = '2024-01-01" OR "1"="1'
        rows = get_species_by_date_safe(self.con, payload)
        self.assertEqual(rows, [], "Injection payload should match no rows with parameterization")


if __name__ == "__main__":
    unittest.main()
