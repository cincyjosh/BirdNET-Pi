"""
Functional tests for scripts/utils/reporting.py.

External calls (subprocess/sox, sqlite3, requests, PIL) are mocked so
these tests run without audio files, a live database, or network access.
"""
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from unittest import mock

# Stub out optional heavy dependencies before importing reporting
for _mod in ('apprise', 'soundfile', 'requests',
             'inotify', 'inotify.adapters', 'inotify.constants'):
    sys.modules.setdefault(_mod, MagicMock())

from scripts.utils.classes import Detection, ParseFileName  # noqa: E402
from scripts.utils import reporting as reporting_module  # noqa: E402
from scripts.utils.reporting import (  # noqa: E402
    extract_safe, summary, update_json_file, write_to_db,
    write_to_file, write_to_json_file,
)
from tests.helpers import Settings  # noqa: E402

FILE_DATE = datetime.datetime(2024, 6, 15, 7, 30, 0)
SETTINGS = Settings.with_defaults()
SETTINGS.update({
    "AUDIOFMT": "mp3",
    "EXTRACTED": "/tmp/birdnet_test_extracted",
    "RECORDING_LENGTH": "15",
    "EXTRACTION_LENGTH": "6",
    "LATITUDE": "42.36",
    "LONGITUDE": "-71.06",
    "SENSITIVITY": "1.25",
    "OVERLAP": "0.0",
    "CONFIDENCE": "0.7",
    "RAW_SPECTROGRAM": "0",
    "BIRDWEATHER_ID": "",
    "HEARTBEAT_URL": "",
})


def make_detection(start=3.0, stop=6.0, sci='Turdus migratorius',
                   common='American Robin', confidence=0.85):
    return Detection(FILE_DATE, start, stop, sci, common, confidence)


def make_parse_file(path='/tmp/2024-06-15-birdnet-07:30:00.wav'):
    return ParseFileName(path)


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------

class TestSummary(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(reporting_module, 'get_settings', return_value=SETTINGS)
        self.patcher.start()
        self.summary = summary

    def tearDown(self):
        self.patcher.stop()

    def test_returns_string(self):
        det = make_detection()
        result = self.summary(make_parse_file(), det)
        self.assertIsInstance(result, str)

    def test_semicolon_delimited(self):
        det = make_detection()
        result = self.summary(make_parse_file(), det)
        parts = result.split(';')
        self.assertEqual(len(parts), 11)

    def test_date_is_first_field(self):
        det = make_detection(start=0.0)
        result = self.summary(make_parse_file(), det)
        self.assertEqual(result.split(';')[0], '2024-06-15')

    def test_sci_name_present(self):
        det = make_detection(sci='Turdus migratorius')
        result = self.summary(make_parse_file(), det)
        self.assertIn('Turdus migratorius', result)

    def test_common_name_present(self):
        det = make_detection(common='American Robin')
        result = self.summary(make_parse_file(), det)
        self.assertIn('American Robin', result)

    def test_confidence_present(self):
        det = make_detection(confidence=0.85)
        result = self.summary(make_parse_file(), det)
        self.assertIn('0.85', result)

    def test_lat_lon_from_config(self):
        det = make_detection()
        result = self.summary(make_parse_file(), det)
        self.assertIn('42.36', result)
        self.assertIn('-71.06', result)


# ---------------------------------------------------------------------------
# write_to_json_file() / update_json_file()
# ---------------------------------------------------------------------------

class TestWriteToJsonFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.patcher = patch.object(reporting_module, 'get_settings', return_value=SETTINGS)
        self.patcher.start()
        self.write_to_json_file = write_to_json_file

    def tearDown(self):
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _file_and_detections(self):
        wav = os.path.join(self.tmpdir, '2024-06-15-birdnet-07:30:00.wav')
        open(wav, 'w').close()
        pf = ParseFileName(wav)
        dets = [make_detection(start=3.0), make_detection(start=6.0, sci='Cyanocitta cristata', common='Blue Jay')]
        for d in dets:
            d.file_name_extr = 'some_file.mp3'
        return pf, dets

    def test_creates_json_file(self):
        pf, dets = self._file_and_detections()
        self.write_to_json_file(pf, dets)
        self.assertTrue(os.path.exists(pf.file_name + '.json'))

    def test_json_is_valid(self):
        pf, dets = self._file_and_detections()
        self.write_to_json_file(pf, dets)
        with open(pf.file_name + '.json') as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_json_has_required_keys(self):
        pf, dets = self._file_and_detections()
        self.write_to_json_file(pf, dets)
        with open(pf.file_name + '.json') as f:
            data = json.load(f)
        for key in ('file_name', 'timestamp', 'delay', 'detections'):
            self.assertIn(key, data)

    def test_detection_count_matches(self):
        pf, dets = self._file_and_detections()
        self.write_to_json_file(pf, dets)
        with open(pf.file_name + '.json') as f:
            data = json.load(f)
        self.assertEqual(len(data['detections']), 2)

    def test_detection_has_common_name_and_confidence(self):
        pf, dets = self._file_and_detections()
        self.write_to_json_file(pf, dets)
        with open(pf.file_name + '.json') as f:
            data = json.load(f)
        det_entry = data['detections'][0]
        self.assertIn('common_name', det_entry)
        self.assertIn('confidence', det_entry)

    def test_empty_detections_list(self):
        pf, _ = self._file_and_detections()
        self.write_to_json_file(pf, [])
        with open(pf.file_name + '.json') as f:
            data = json.load(f)
        self.assertEqual(data['detections'], [])


class TestUpdateJsonFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.patcher = patch.object(reporting_module, 'get_settings', return_value=SETTINGS)
        self.patcher.start()
        self.update_json_file = update_json_file

    def tearDown(self):
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deletes_existing_json_and_writes_new(self):
        wav = os.path.join(self.tmpdir, '2024-06-15-birdnet-07:30:00.wav')
        open(wav, 'w').close()
        old_json = os.path.join(self.tmpdir, 'old_result.json')
        open(old_json, 'w').close()

        pf = ParseFileName(wav)
        self.update_json_file(pf, [])

        self.assertFalse(os.path.exists(old_json))
        self.assertTrue(os.path.exists(wav + '.json'))


# ---------------------------------------------------------------------------
# write_to_db()
# ---------------------------------------------------------------------------

class TestWriteToDb(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(reporting_module, 'get_settings', return_value=SETTINGS)
        self.patcher.start()
        self.write_to_db = write_to_db

    def tearDown(self):
        self.patcher.stop()

    def _make_db_and_detection(self):
        con = sqlite3.connect(':memory:')
        con.execute("""CREATE TABLE detections (
            Date TEXT, Time TEXT, Sci_Name TEXT, Com_Name TEXT,
            Confidence REAL, Lat TEXT, Lon TEXT, Cutoff TEXT,
            Week TEXT, Sens TEXT, Overlap TEXT, File_Name TEXT
        )""")
        con.commit()
        det = make_detection()
        det.file_name_extr = '/tmp/Robin-85-2024-06-15-birdnet-07:30:00.mp3'
        return con, det

    def test_inserts_row_into_db(self):
        mock_con = MagicMock()
        det = make_detection()
        det.file_name_extr = '/tmp/Robin-85-2024-06-15-birdnet-07:30:00.mp3'
        with patch('scripts.utils.reporting.sqlite3.connect', return_value=mock_con):
            self.write_to_db(make_parse_file(), det)
        # INSERT goes through con.cursor().execute(...)
        cur = mock_con.cursor.return_value
        cur.execute.assert_called_once()
        self.assertIn('INSERT INTO detections', cur.execute.call_args[0][0])

    def test_inserted_row_has_correct_species(self):
        mock_con = MagicMock()
        det = make_detection(sci='Turdus migratorius')
        det.file_name_extr = '/tmp/Robin-85-2024-06-15-birdnet-07:30:00.mp3'
        with patch('scripts.utils.reporting.sqlite3.connect', return_value=mock_con):
            self.write_to_db(make_parse_file(), det)
        cur = mock_con.cursor.return_value
        values = cur.execute.call_args[0][1]
        self.assertIn('Turdus migratorius', values)

    def test_retries_on_db_lock_then_succeeds(self):
        """Simulate a locked DB on first attempt, success on second."""
        con, det = self._make_db_and_detection()
        call_count = [0]
        real_connect = sqlite3.connect

        def flaky_connect(*args, **kwargs):
            call_count[0] += 1
            c = real_connect(':memory:')
            c.execute("""CREATE TABLE detections (
                Date TEXT, Time TEXT, Sci_Name TEXT, Com_Name TEXT,
                Confidence REAL, Lat TEXT, Lon TEXT, Cutoff TEXT,
                Week TEXT, Sens TEXT, Overlap TEXT, File_Name TEXT
            )""")
            if call_count[0] == 1:
                raise sqlite3.OperationalError('database is locked')
            return c

        with patch('scripts.utils.reporting.DB_PATH', ':memory:'), \
             patch('sqlite3.connect', side_effect=flaky_connect), \
             patch('scripts.utils.reporting.sleep'):
            self.write_to_db(make_parse_file(), det)

        self.assertEqual(call_count[0], 2)

    def test_connection_closed_after_insert(self):
        mock_con = MagicMock()
        mock_con.execute.return_value = MagicMock()
        with patch('scripts.utils.reporting.DB_PATH', ':memory:'), \
             patch('sqlite3.connect', return_value=mock_con):
            self.write_to_db(make_parse_file(), make_detection())
        mock_con.close.assert_called()

    def test_connection_closed_even_on_error(self):
        mock_con = MagicMock()
        mock_con.execute.side_effect = sqlite3.OperationalError('locked')
        with patch('scripts.utils.reporting.DB_PATH', ':memory:'), \
             patch('sqlite3.connect', return_value=mock_con), \
             patch('scripts.utils.reporting.sleep'):
            self.write_to_db(make_parse_file(), make_detection())
        mock_con.close.assert_called()


# ---------------------------------------------------------------------------
# write_to_file()
# ---------------------------------------------------------------------------

class TestWriteToFile(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(reporting_module, 'get_settings', return_value=SETTINGS)
        self.patcher.start()
        self.write_to_file = write_to_file

    def tearDown(self):
        self.patcher.stop()

    def test_appends_line_to_birddb(self):
        det = make_detection()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            tmp = f.name
        try:
            with patch('builtins.open', mock.mock_open()) as m:
                self.write_to_file(make_parse_file(), det)
            handle = m()
            written = handle.write.call_args[0][0]
            self.assertIn('Turdus migratorius', written)
            self.assertTrue(written.endswith('\n'))
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# extract_safe() — spacer padding logic
# ---------------------------------------------------------------------------

class TestExtractSafe(unittest.TestCase):

    def setUp(self):
        self.patcher = patch.object(reporting_module, 'get_settings', return_value=SETTINGS)
        self.patcher.start()
        self.extract_safe = extract_safe

    def tearDown(self):
        self.patcher.stop()

    def test_pads_start_with_spacer(self):
        """With EXTRACTION_LENGTH=6, spacer=(6-3)/2=1.5; start=3 → safe_start=1.5"""
        with patch.object(reporting_module, 'extract') as mock_extract:
            self.extract_safe('in.wav', 'out.wav', start=3.0, stop=6.0)
            _, _, safe_start, safe_stop = mock_extract.call_args[0]
            self.assertAlmostEqual(safe_start, 1.5)

    def test_pads_stop_with_spacer(self):
        """stop=6 + spacer=1.5 → safe_stop=7.5"""
        with patch.object(reporting_module, 'extract') as mock_extract:
            self.extract_safe('in.wav', 'out.wav', start=3.0, stop=6.0)
            _, _, safe_start, safe_stop = mock_extract.call_args[0]
            self.assertAlmostEqual(safe_stop, 7.5)

    def test_safe_start_clamped_to_zero(self):
        """Detection starting at 0 should not produce a negative safe_start."""
        with patch.object(reporting_module, 'extract') as mock_extract:
            self.extract_safe('in.wav', 'out.wav', start=0.0, stop=3.0)
            _, _, safe_start, _ = mock_extract.call_args[0]
            self.assertGreaterEqual(safe_start, 0.0)

    def test_safe_stop_clamped_to_recording_length(self):
        """Detection near end of recording should not exceed RECORDING_LENGTH."""
        with patch.object(reporting_module, 'extract') as mock_extract:
            self.extract_safe('in.wav', 'out.wav', start=12.0, stop=15.0)
            _, _, _, safe_stop = mock_extract.call_args[0]
            self.assertLessEqual(safe_stop, 15)

    def test_invalid_extraction_length_defaults_to_6(self):
        """If EXTRACTION_LENGTH is non-numeric, spacer defaults to (6-3)/2=1.5"""
        bad_settings = Settings(SETTINGS)
        bad_settings['EXTRACTION_LENGTH'] = 'bad'
        with patch.object(reporting_module, 'get_settings', return_value=bad_settings), \
             patch.object(reporting_module, 'extract') as mock_extract:
            self.extract_safe('in.wav', 'out.wav', start=3.0, stop=6.0)
            _, _, safe_start, _ = mock_extract.call_args[0]
            self.assertAlmostEqual(safe_start, 1.5)


if __name__ == '__main__':
    unittest.main()
