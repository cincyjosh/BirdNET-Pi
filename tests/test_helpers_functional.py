import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.utils.helpers import PHPConfigParser, _load_settings, get_font

# daily_plot uses bare 'utils.*' imports relative to scripts/; add that to path
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, _SCRIPTS_DIR)
from daily_plot import wrap_width  # noqa: E402
sys.path.pop(0)


MINIMAL_CONF = """\
RECS_DIR="/home/pi/BirdSongs"
DATABASE_LANG="en"
MODEL="BirdNET_GLOBAL_6K_V2.4_Model_FP16"
CONFIDENCE="0.7"
RECORDING_LENGTH="15"
EXTRACTION_LENGTH="6"
SENSITIVITY="1.25"
OVERLAP="0.0"
LATITUDE="42.3601"
LONGITUDE="-71.0589"
COLOR_SCHEME="light"
AUDIOFMT="mp3"
BIRDWEATHER_ID=""
HEARTBEAT_URL=""
RAW_SPECTROGRAM="0"
"""


def make_conf_file(content=MINIMAL_CONF):
    fd, path = tempfile.mkstemp(suffix='.conf')
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    return path


class TestPHPConfigParser(unittest.TestCase):

    def _parser_with(self, content):
        from itertools import chain
        parser = PHPConfigParser(interpolation=None)
        parser.optionxform = lambda option: option
        lines = chain(('[top]',), content.splitlines(keepends=True))
        parser.read_file(lines)
        return parser['top']

    def test_quoted_string_value_stripped(self):
        p = self._parser_with('KEY="hello"\n')
        self.assertEqual(p.get('KEY'), 'hello')

    def test_unquoted_value_returned_as_is(self):
        p = self._parser_with('KEY=hello\n')
        self.assertEqual(p.get('KEY'), 'hello')

    def test_empty_quoted_value_returns_empty_string(self):
        p = self._parser_with('KEY=""\n')
        self.assertEqual(p.get('KEY'), '')

    def test_raw_flag_preserves_quotes(self):
        p = self._parser_with('KEY="hello"\n')
        self.assertEqual(p.get('KEY', raw=True), '"hello"')

    def test_numeric_string_value(self):
        p = self._parser_with('CONFIDENCE="0.7"\n')
        self.assertEqual(p.get('CONFIDENCE'), '0.7')

    def test_fallback_used_for_missing_key(self):
        p = self._parser_with('KEY="val"\n')
        result = p.get('MISSING', fallback='default')
        self.assertEqual(result, 'default')


class TestLoadSettings(unittest.TestCase):

    def setUp(self):
        # Clear the module-level cache before each test
        import scripts.utils.helpers as h
        h._settings = None

    def tearDown(self):
        import scripts.utils.helpers as h
        h._settings = None

    def test_returns_section_proxy(self):
        path = make_conf_file()
        try:
            s = _load_settings(path)
            self.assertEqual(s['DATABASE_LANG'], 'en')
        finally:
            os.unlink(path)

    def test_quoted_values_stripped(self):
        path = make_conf_file()
        try:
            s = _load_settings(path)
            self.assertEqual(s['RECS_DIR'], '/home/pi/BirdSongs')
        finally:
            os.unlink(path)

    def test_numeric_value_accessible_as_string(self):
        path = make_conf_file()
        try:
            s = _load_settings(path)
            self.assertEqual(s['CONFIDENCE'], '0.7')
        finally:
            os.unlink(path)

    def test_cached_on_second_call(self):
        path = make_conf_file()
        try:
            s1 = _load_settings(path)
            s2 = _load_settings(path)
            self.assertIs(s1, s2)
        finally:
            os.unlink(path)

    def test_force_reload_reads_fresh_file(self):
        path = make_conf_file()
        try:
            _load_settings(path)
            # Overwrite the file with different content
            with open(path, 'w') as f:
                f.write(MINIMAL_CONF.replace('"en"', '"de"'))
            s2 = _load_settings(path, force_reload=True)
            self.assertEqual(s2['DATABASE_LANG'], 'de')
        finally:
            os.unlink(path)

    def test_getint_works_on_result(self):
        path = make_conf_file()
        try:
            s = _load_settings(path)
            self.assertEqual(s.getint('RECORDING_LENGTH'), 15)
        finally:
            os.unlink(path)

    def test_getfloat_works_on_result(self):
        path = make_conf_file()
        try:
            s = _load_settings(path)
            self.assertAlmostEqual(s.getfloat('CONFIDENCE'), 0.7)
        finally:
            os.unlink(path)


class TestGetFont(unittest.TestCase):

    def _settings(self, lang):
        import scripts.utils.helpers as h
        h._settings = None
        path = make_conf_file(MINIMAL_CONF.replace('"en"', f'"{lang}"'))
        s = _load_settings(path)
        os.unlink(path)
        return s

    def tearDown(self):
        import scripts.utils.helpers as h
        h._settings = None

    def test_english_returns_roboto(self):
        with patch('scripts.utils.helpers.get_settings',
                   return_value=self._settings('en')):
            f = get_font()
        self.assertEqual(f['font.family'], 'Roboto Flex')

    def test_arabic_returns_noto_arabic(self):
        with patch('scripts.utils.helpers.get_settings',
                   return_value=self._settings('ar')):
            f = get_font()
        self.assertEqual(f['font.family'], 'Noto Sans Arabic')

    def test_japanese_returns_noto_jp(self):
        with patch('scripts.utils.helpers.get_settings',
                   return_value=self._settings('ja')):
            f = get_font()
        self.assertEqual(f['font.family'], 'Noto Sans JP')

    def test_korean_returns_noto_kr(self):
        with patch('scripts.utils.helpers.get_settings',
                   return_value=self._settings('ko')):
            f = get_font()
        self.assertEqual(f['font.family'], 'Noto Sans KR')

    def test_thai_returns_noto_thai(self):
        with patch('scripts.utils.helpers.get_settings',
                   return_value=self._settings('th')):
            f = get_font()
        self.assertEqual(f['font.family'], 'Noto Sans Thai')

    def test_font_dict_has_path_key(self):
        with patch('scripts.utils.helpers.get_settings',
                   return_value=self._settings('en')):
            f = get_font()
        self.assertIn('path', f)


class TestWrapWidth(unittest.TestCase):

    def test_empty_string_returns_base(self):
        self.assertEqual(wrap_width(''), 16)

    def test_wide_chars_reduce_width(self):
        # Each M/W/m/w subtracts 0.33
        result = wrap_width('MMM')
        self.assertLess(result, 16)

    def test_narrow_chars_increase_width(self):
        # Each I/i/j/l adds 0.33
        result = wrap_width('iii')
        self.assertGreater(result, 16)

    def test_mixed_chars_average_out(self):
        # 3 M's and 3 i's cancel each other
        result = wrap_width('MiMiMi')
        self.assertEqual(result, 16)

    def test_returns_integer(self):
        self.assertIsInstance(wrap_width('American Robin'), int)


if __name__ == '__main__':
    unittest.main()
