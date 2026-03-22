"""
Functional tests for scripts/daily_plot.py.

Database access and matplotlib rendering are mocked so no real DB,
audio files, or display is needed.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pandas as pd

# daily_plot uses bare 'utils.*' imports relative to scripts/
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, _SCRIPTS_DIR)
import daily_plot as dp  # noqa: E402
sys.path.pop(0)

from tests.helpers import Settings  # noqa: E402

SETTINGS = Settings.with_defaults()
SETTINGS.update({
    "COLOR_SCHEME": "light",
    "RECS_DIR": "/tmp/birdtest",
    "RECORDING_LENGTH": "15",
    "EXTRACTION_LENGTH": "6",
})

NOW = datetime(2024, 6, 15, 8, 10, 0)


def _make_df(*species):
    """Build a minimal detections DataFrame like get_data() returns."""
    rows = []
    for i, (sci, com, hour) in enumerate(species):
        rows.append({
            'Date': pd.Timestamp('2024-06-15'),
            'Time': pd.Timestamp('2024-06-15 {:02d}:00:00'.format(hour)),
            'Sci_Name': sci,
            'Com_Name': com,
            'Confidence': 0.8,
            'Hour of Day': hour,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# wrap_width
# ---------------------------------------------------------------------------

class TestWrapWidth(unittest.TestCase):

    def test_base_width_empty_string(self):
        self.assertEqual(dp.wrap_width(''), 16)

    def test_wide_chars_reduce_width(self):
        self.assertLess(dp.wrap_width('MMMM'), 16)

    def test_narrow_chars_increase_width(self):
        self.assertGreater(dp.wrap_width('iiii'), 16)

    def test_returns_integer(self):
        self.assertIsInstance(dp.wrap_width('American Robin'), int)

    def test_balanced_chars_stay_near_16(self):
        # 3 M's (each -0.33) and 3 i's (each +0.33) cancel
        self.assertEqual(dp.wrap_width('MiMiMi'), 16)


# ---------------------------------------------------------------------------
# get_data
# ---------------------------------------------------------------------------

class TestGetData(unittest.TestCase):

    def _fake_read_sql(self, query, conn):
        return pd.DataFrame({
            'Date': pd.to_datetime(['2024-06-15', '2024-06-15']),
            'Time': pd.to_datetime(['07:00:00', '08:30:00'], format='%H:%M:%S'),
            'Sci_Name': ['Turdus migratorius', 'Cyanocitta cristata'],
            'Com_Name': ['American Robin', 'Blue Jay'],
            'Confidence': [0.85, 0.72],
        })

    def test_returns_dataframe_and_datetime(self):
        with patch('sqlite3.connect'), \
             patch('pandas.read_sql_query', side_effect=self._fake_read_sql):
            df, ts = dp.get_data(NOW)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertIsInstance(ts, datetime)

    def test_hour_of_day_column_added(self):
        with patch('sqlite3.connect'), \
             patch('pandas.read_sql_query', side_effect=self._fake_read_sql):
            df, _ = dp.get_data(NOW)
        self.assertIn('Hour of Day', df.columns)

    def test_hour_of_day_values_are_integers(self):
        with patch('sqlite3.connect'), \
             patch('pandas.read_sql_query', side_effect=self._fake_read_sql):
            df, _ = dp.get_data(NOW)
        self.assertTrue(all(isinstance(h, int) for h in df['Hour of Day']))

    def test_uses_provided_datetime(self):
        captured = []

        def fake_read(query, conn):
            captured.append(query)
            return self._fake_read_sql(query, conn)

        with patch('sqlite3.connect'), \
             patch('pandas.read_sql_query', side_effect=fake_read):
            dp.get_data(NOW)
        self.assertIn('2024-06-15', captured[0])

    def test_defaults_to_today_when_no_date_given(self):
        today = datetime.now().strftime('%Y-%m-%d')
        captured = []

        def fake_read(query, conn):
            captured.append(query)
            return self._fake_read_sql(query, conn)

        with patch('sqlite3.connect'), \
             patch('pandas.read_sql_query', side_effect=fake_read):
            dp.get_data()
        self.assertIn(today, captured[0])


# ---------------------------------------------------------------------------
# create_plot — file path and name
# ---------------------------------------------------------------------------

class TestCreatePlotOutputPath(unittest.TestCase):
    """Verify create_plot saves to the correct filename without rendering."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.saved_paths = []

        def fake_savefig(path):
            self.saved_paths.append(path)

        self._patches = [
            patch.object(dp, 'get_settings', return_value=SETTINGS),
            patch('matplotlib.pyplot.savefig', side_effect=fake_savefig),
            patch('matplotlib.pyplot.show'),
            patch('matplotlib.pyplot.close'),
            patch('matplotlib.pyplot.subplots', return_value=(MagicMock(), [MagicMock(), MagicMock()])),
            patch('seaborn.countplot', return_value=MagicMock()),
            patch('seaborn.heatmap', return_value=MagicMock()),
            patch('matplotlib.pyplot.suptitle'),
            patch('matplotlib.pyplot.Normalize', return_value=MagicMock(return_value=[0.5])),
            patch('os.path.expanduser', side_effect=lambda p: p.replace('~', self.tmpdir)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _simple_df(self, n_species=3):
        species = [
            ('Turdus migratorius', 'American Robin', 7),
            ('Cyanocitta cristata', 'Blue Jay', 8),
            ('Spinus tristis', 'American Goldfinch', 8),
        ][:n_species]
        return _make_df(*species)

    def test_combo_saved_with_correct_name(self):
        df = self._simple_df()
        dp.create_plot(df, NOW)
        self.assertTrue(any('Combo-2024-06-15.png' in p for p in self.saved_paths))

    def test_combo2_saved_with_correct_name(self):
        df = self._simple_df()
        dp.create_plot(df, NOW, is_top=False)
        self.assertTrue(any('Combo2-2024-06-15.png' in p for p in self.saved_paths))

    def test_combo_not_combo2_when_is_top_none(self):
        df = self._simple_df()
        dp.create_plot(df, NOW)
        self.assertFalse(any('Combo2' in p for p in self.saved_paths))


# ---------------------------------------------------------------------------
# main — Combo2 threshold logic
# ---------------------------------------------------------------------------

class TestMainCombo2Threshold(unittest.TestCase):
    """main() should only generate Combo2 when there are >10 unique species."""

    def _run_main(self, n_species):
        species_list = [(f'Species sci {i}', f'Species com {i}', 7) for i in range(n_species)]
        df = _make_df(*species_list)

        created_plots = []

        def fake_create_plot(data, time, is_top=None):
            created_plots.append(is_top)

        with patch.object(dp, 'get_data', return_value=(df, NOW)), \
             patch.object(dp, 'create_plot', side_effect=fake_create_plot), \
             patch.object(dp, 'load_fonts'):
            dp.main(daemon=False, sleep_m=2)

        return created_plots

    def test_combo_always_generated(self):
        calls = self._run_main(n_species=5)
        self.assertIn(None, calls)

    def test_combo2_not_generated_with_few_species(self):
        calls = self._run_main(n_species=5)
        self.assertNotIn(False, calls)

    def test_combo2_generated_with_many_species(self):
        calls = self._run_main(n_species=11)
        self.assertIn(False, calls)

    def test_combo2_threshold_is_10(self):
        exactly_10 = self._run_main(n_species=10)
        exactly_11 = self._run_main(n_species=11)
        self.assertNotIn(False, exactly_10)
        self.assertIn(False, exactly_11)

    def test_empty_dataset_skips_plot(self):
        empty_df = pd.DataFrame()
        created_plots = []

        with patch.object(dp, 'get_data', return_value=(empty_df, NOW)), \
             patch.object(dp, 'create_plot', side_effect=lambda *a, **k: created_plots.append(1)), \
             patch.object(dp, 'load_fonts'):
            dp.main(daemon=False, sleep_m=2)

        self.assertEqual(created_plots, [])


if __name__ == '__main__':
    unittest.main()
