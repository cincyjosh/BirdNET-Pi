import datetime
import unittest

from scripts.utils.classes import Detection, ParseFileName


FILE_DATE = datetime.datetime(2024, 6, 15, 7, 30, 0)


class TestDetectionInit(unittest.TestCase):

    def _make(self, start=3.0, stop=6.0, sci='Turdus migratorius',
              common='American Robin', confidence=0.8531):
        return Detection(FILE_DATE, start, stop, sci, common, confidence)

    def test_start_stop_stored_as_float(self):
        d = self._make(start='3', stop='6')
        self.assertEqual(d.start, 3.0)
        self.assertEqual(d.stop, 6.0)

    def test_datetime_offset_by_start(self):
        d = self._make(start=5.0)
        expected = FILE_DATE + datetime.timedelta(seconds=5.0)
        self.assertEqual(d.datetime, expected)

    def test_date_and_time_strings(self):
        d = self._make(start=0.0)
        self.assertEqual(d.date, '2024-06-15')
        self.assertEqual(d.time, '07:30:00')

    def test_date_string_rolls_over_at_midnight(self):
        # start offset pushes time past midnight
        d = Detection(
            datetime.datetime(2024, 6, 15, 23, 59, 55),
            6.0, 9.0, 'Sp sci', 'Sp common', 0.9
        )
        self.assertEqual(d.date, '2024-06-16')

    def test_week_number(self):
        d = self._make()
        # 2024-06-15 is ISO week 24
        self.assertEqual(d.week, 24)

    def test_confidence_rounded_to_4dp(self):
        d = self._make(confidence=0.853123456)
        self.assertEqual(d.confidence, 0.8531)

    def test_confidence_pct_is_integer_percent(self):
        d = self._make(confidence=0.8531)
        self.assertEqual(d.confidence_pct, 85)

    def test_confidence_pct_rounds_correctly(self):
        d = self._make(confidence=0.756)
        self.assertEqual(d.confidence_pct, 76)

    def test_species_and_scientific_name_identical(self):
        d = self._make(sci='Cyanocitta cristata')
        self.assertEqual(d.species, 'Cyanocitta cristata')
        self.assertEqual(d.scientific_name, 'Cyanocitta cristata')

    def test_common_name_stored(self):
        d = self._make(common="Steller's Jay")
        self.assertEqual(d.common_name, "Steller's Jay")

    def test_common_name_safe_strips_apostrophe(self):
        d = self._make(common="Steller's Jay")
        self.assertNotIn("'", d.common_name_safe)

    def test_common_name_safe_replaces_spaces_with_underscores(self):
        d = self._make(common='American Robin')
        self.assertEqual(d.common_name_safe, 'American_Robin')

    def test_common_name_safe_combined(self):
        d = self._make(common="Steller's Jay")
        self.assertEqual(d.common_name_safe, 'Stellers_Jay')

    def test_file_name_extr_initially_none(self):
        d = self._make()
        self.assertIsNone(d.file_name_extr)

    def test_iso8601_is_string(self):
        d = self._make()
        self.assertIsInstance(d.iso8601, str)

    def test_iso8601_contains_date(self):
        d = self._make(start=0.0)
        self.assertIn('2024-06-15', d.iso8601)

    def test_str_contains_species_and_confidence(self):
        d = self._make(sci='Turdus migratorius', confidence=0.85)
        s = str(d)
        self.assertIn('Turdus migratorius', s)
        self.assertIn('0.85', s)


class TestParseFileName(unittest.TestCase):

    STANDARD = '/home/pi/BirdSongs/StreamData/2024-06-15-birdnet-07:30:00.wav'
    RTSP = '/home/pi/BirdSongs/StreamData/2024-06-15-birdnet-RTSP_1-07:30:00.wav'
    RTSP2 = '/home/pi/BirdSongs/StreamData/2024-06-15-birdnet-RTSP_2-07:30:00.wav'

    def test_file_name_stored(self):
        p = ParseFileName(self.STANDARD)
        self.assertEqual(p.file_name, self.STANDARD)

    def test_file_date_parsed(self):
        p = ParseFileName(self.STANDARD)
        self.assertEqual(p.file_date, datetime.datetime(2024, 6, 15, 7, 30, 0))

    def test_no_rtsp_id_is_empty_string(self):
        p = ParseFileName(self.STANDARD)
        self.assertEqual(p.RTSP_id, '')

    def test_rtsp_id_extracted(self):
        p = ParseFileName(self.RTSP)
        self.assertEqual(p.RTSP_id, 'RTSP_1-')

    def test_rtsp_id_2_extracted(self):
        p = ParseFileName(self.RTSP2)
        self.assertEqual(p.RTSP_id, 'RTSP_2-')

    def test_week_property(self):
        p = ParseFileName(self.STANDARD)
        # 2024-06-15 is ISO week 24
        self.assertEqual(p.week, 24)

    def test_week_property_first_week(self):
        p = ParseFileName('/tmp/2024-01-01-birdnet-00:00:00.wav')
        self.assertEqual(p.week, 1)

    def test_iso8601_property_returns_string(self):
        p = ParseFileName(self.STANDARD)
        self.assertIsInstance(p.iso8601, str)

    def test_iso8601_property_contains_date(self):
        p = ParseFileName(self.STANDARD)
        self.assertIn('2024-06-15', p.iso8601)

    def test_root_is_basename_without_extension(self):
        p = ParseFileName(self.STANDARD)
        self.assertEqual(p.root, '2024-06-15-birdnet-07:30:00')


if __name__ == '__main__':
    unittest.main()
