"""
Functional tests for scripts/utils/db.py.

All tests use an in-memory SQLite database injected via the module-level
_DB global so no real birds.db is required.
"""
import sqlite3
import unittest
from datetime import datetime, timedelta

import scripts.utils.db as db_module
from scripts.utils.db import (
    get_record,
    get_records,
    get_latest,
    get_species_by,
    get_summary,
    get_this_weeks_count_for,
    get_todays_count_for,
)

SCHEMA = """
CREATE TABLE detections (
    Date        TEXT,
    Time        TEXT,
    Sci_Name    TEXT,
    Com_Name    TEXT,
    Confidence  REAL,
    Lat         TEXT,
    Lon         TEXT,
    Cutoff      TEXT,
    Week        TEXT,
    Sens        TEXT,
    Overlap     TEXT,
    File_Name   TEXT
)
"""

TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
EIGHT_DAYS_AGO = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")


def make_db(*rows):
    """Create an in-memory SQLite connection pre-populated with rows.

    Each row is a tuple:
      (date, time, sci_name, com_name, confidence, file_name)
    Remaining detection columns are filled with placeholders.
    """
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    for row in rows:
        date, time, sci, com, conf, fname = row
        con.execute(
            "INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (date, time, sci, com, conf, '0', '0', '0.7', '1', '1.25', '0.0', fname)
        )
    con.commit()
    return con


class DbTestCase(unittest.TestCase):
    """Base class: replaces the module-level _DB with an in-memory DB."""

    def setUp(self):
        self._orig_db = db_module._DB
        db_module._DB = self.make_test_db()

    def tearDown(self):
        if db_module._DB is not None:
            db_module._DB.close()
        db_module._DB = self._orig_db

    def make_test_db(self):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# get_records / get_record
# ---------------------------------------------------------------------------

class TestGetRecords(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (TODAY, '09:00:00', 'Cyanocitta cristata', 'Blue Jay', 0.72, 'f2.wav'),
        )

    def test_returns_all_rows(self):
        rows = get_records("SELECT * FROM detections")
        self.assertEqual(len(rows), 2)

    def test_returns_empty_list_on_no_match(self):
        rows = get_records("SELECT * FROM detections WHERE Sci_Name = ?", ('Nonexistent',))
        self.assertEqual(rows, [])

    def test_params_filter_correctly(self):
        rows = get_records("SELECT * FROM detections WHERE Sci_Name = ?", ('Turdus migratorius',))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Com_Name'], 'American Robin')

    def test_returns_empty_list_on_sql_error(self):
        rows = get_records("SELECT * FROM nonexistent_table")
        self.assertEqual(rows, [])

    def test_row_fields_accessible_by_name(self):
        rows = get_records("SELECT * FROM detections ORDER BY Time")
        self.assertEqual(rows[0]['Sci_Name'], 'Turdus migratorius')


class TestGetRecord(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (TODAY, '09:00:00', 'Cyanocitta cristata', 'Blue Jay', 0.72, 'f2.wav'),
        )

    def test_returns_first_row_as_dict(self):
        row = get_record("SELECT * FROM detections ORDER BY Time")
        self.assertIsInstance(row, dict)
        self.assertEqual(row['Com_Name'], 'American Robin')

    def test_returns_none_when_no_rows(self):
        row = get_record("SELECT * FROM detections WHERE Sci_Name = ?", ('Nobody',))
        self.assertIsNone(row)


# ---------------------------------------------------------------------------
# get_latest
# ---------------------------------------------------------------------------

class TestGetLatest(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (TODAY, '09:30:00', 'Cyanocitta cristata', 'Blue Jay', 0.72, 'f2.wav'),
            (YESTERDAY, '22:00:00', 'Melospiza melodia', 'Song Sparrow', 0.91, 'f3.wav'),
        )

    def test_returns_most_recent_by_date_then_time(self):
        row = get_latest()
        self.assertEqual(row['Sci_Name'], 'Cyanocitta cristata')
        self.assertEqual(row['Time'], '09:30:00')

    def test_returns_dict(self):
        self.assertIsInstance(get_latest(), dict)


class TestGetLatestEmptyDb(DbTestCase):

    def make_test_db(self):
        return make_db()

    def test_returns_none_on_empty_db(self):
        self.assertIsNone(get_latest())


# ---------------------------------------------------------------------------
# get_todays_count_for
# ---------------------------------------------------------------------------

class TestGetTodaysCountFor(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (TODAY, '09:00:00', 'Turdus migratorius', 'American Robin', 0.78, 'f2.wav'),
            (TODAY, '10:00:00', 'Cyanocitta cristata', 'Blue Jay', 0.72, 'f3.wav'),
            (YESTERDAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.90, 'f4.wav'),
        )

    def test_counts_only_todays_detections(self):
        self.assertEqual(get_todays_count_for('Turdus migratorius'), 2)

    def test_excludes_other_species(self):
        self.assertEqual(get_todays_count_for('Cyanocitta cristata'), 1)

    def test_returns_zero_for_unknown_species(self):
        self.assertEqual(get_todays_count_for('Nobody here'), 0)

    def test_excludes_yesterday(self):
        # Robin has 2 today + 1 yesterday; should return 2
        self.assertEqual(get_todays_count_for('Turdus migratorius'), 2)


# ---------------------------------------------------------------------------
# get_this_weeks_count_for
# ---------------------------------------------------------------------------

class TestGetThisWeeksCountFor(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (YESTERDAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.90, 'f2.wav'),
            (EIGHT_DAYS_AGO, '08:00:00', 'Turdus migratorius', 'American Robin', 0.77, 'f3.wav'),
        )

    def test_includes_today_and_yesterday(self):
        count = get_this_weeks_count_for('Turdus migratorius')
        self.assertEqual(count, 2)

    def test_excludes_detections_older_than_7_days(self):
        # Eight days ago should not be counted
        count = get_this_weeks_count_for('Turdus migratorius')
        self.assertLess(count, 3)

    def test_returns_zero_for_unknown_species(self):
        self.assertEqual(get_this_weeks_count_for('Fictional Bird'), 0)


# ---------------------------------------------------------------------------
# get_species_by
# ---------------------------------------------------------------------------

class TestGetSpeciesBy(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (TODAY, '09:00:00', 'Turdus migratorius', 'American Robin', 0.78, 'f2.wav'),
            (TODAY, '10:00:00', 'Turdus migratorius', 'American Robin', 0.91, 'f3.wav'),
            (TODAY, '08:30:00', 'Cyanocitta cristata', 'Blue Jay', 0.72, 'f4.wav'),
            (YESTERDAY, '07:00:00', 'Melospiza melodia', 'Song Sparrow', 0.80, 'f5.wav'),
        )

    def test_returns_list(self):
        self.assertIsInstance(get_species_by(), list)

    def test_groups_by_species(self):
        rows = get_species_by()
        # 3 unique species across both dates
        self.assertEqual(len(rows), 3)

    def test_default_sort_is_alphabetical_by_common_name(self):
        rows = get_species_by()
        names = [r['Com_Name'] for r in rows]
        self.assertEqual(names, sorted(names))

    def test_sort_by_occurrences(self):
        rows = get_species_by(sort_by='occurrences')
        counts = [r['Count'] for r in rows]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_sort_by_confidence(self):
        rows = get_species_by(sort_by='confidence')
        confs = [r['MaxConfidence'] for r in rows]
        self.assertEqual(confs, sorted(confs, reverse=True))

    def test_date_filter_excludes_other_dates(self):
        rows = get_species_by(date=TODAY)
        # Song Sparrow was only detected yesterday
        sci_names = [r['Sci_Name'] for r in rows]
        self.assertNotIn('Melospiza melodia', sci_names)

    def test_date_filter_includes_matching_date(self):
        rows = get_species_by(date=TODAY)
        sci_names = [r['Sci_Name'] for r in rows]
        self.assertIn('Turdus migratorius', sci_names)

    def test_count_column_correct(self):
        rows = get_species_by(sort_by='occurrences')
        robin = next(r for r in rows if r['Sci_Name'] == 'Turdus migratorius')
        self.assertEqual(robin['Count'], 3)

    def test_max_confidence_column_correct(self):
        rows = get_species_by()
        robin = next(r for r in rows if r['Sci_Name'] == 'Turdus migratorius')
        self.assertAlmostEqual(robin['MaxConfidence'], 0.91)


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------

class TestGetSummary(DbTestCase):

    def make_test_db(self):
        return make_db(
            (TODAY, '08:00:00', 'Turdus migratorius', 'American Robin', 0.85, 'f1.wav'),
            (TODAY, '09:00:00', 'Cyanocitta cristata', 'Blue Jay', 0.72, 'f2.wav'),
            (YESTERDAY, '07:00:00', 'Melospiza melodia', 'Song Sparrow', 0.80, 'f3.wav'),
        )

    def test_returns_dict(self):
        self.assertIsInstance(get_summary(), dict)

    def test_has_total_count_key(self):
        self.assertIn('total_count', get_summary())

    def test_has_todays_count_key(self):
        self.assertIn('todays_count', get_summary())

    def test_has_species_tally_key(self):
        self.assertIn('species_tally', get_summary())

    def test_total_count_includes_all_rows(self):
        self.assertEqual(get_summary()['total_count'], 3)

    def test_species_tally_counts_distinct_species(self):
        self.assertEqual(get_summary()['species_tally'], 3)


if __name__ == '__main__':
    unittest.main()
