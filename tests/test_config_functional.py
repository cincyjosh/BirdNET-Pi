"""
Functional tests for config parsing and type coercion via helpers.py.

Verifies that birdnet.conf values are accessible with the correct types
and that edge cases (empty values, boolean-like flags) behave as expected.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Stub unavailable modules before any import that might trigger them
for _mod in ('apprise', 'soundfile', 'requests', 'librosa',
             'inotify', 'inotify.adapters', 'inotify.constants'):
    sys.modules.setdefault(_mod, MagicMock())

import scripts.utils.helpers as helpers_module  # noqa: E402
from scripts.utils.helpers import _load_settings  # noqa: E402


FULL_CONF = """\
RECS_DIR="/home/pi/BirdSongs"
EXTRACTED="/home/pi/BirdSongs/Extracted"
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
ICE_PWD="abc123"
PRIVACY_THRESHOLD="0"
SF_THRESH="0.003"
"""


def make_conf(content=FULL_CONF):
    fd, path = tempfile.mkstemp(suffix='.conf')
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    return path


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        helpers_module._settings = None
        self._conf_path = make_conf()
        self.conf = _load_settings(self._conf_path)

    def tearDown(self):
        os.unlink(self._conf_path)
        helpers_module._settings = None


# ---------------------------------------------------------------------------
# String values
# ---------------------------------------------------------------------------

class TestStringValues(ConfigTestCase):

    def test_recs_dir_no_quotes(self):
        self.assertEqual(self.conf['RECS_DIR'], '/home/pi/BirdSongs')

    def test_database_lang(self):
        self.assertEqual(self.conf['DATABASE_LANG'], 'en')

    def test_model_name(self):
        self.assertEqual(self.conf['MODEL'], 'BirdNET_GLOBAL_6K_V2.4_Model_FP16')

    def test_audiofmt(self):
        self.assertEqual(self.conf['AUDIOFMT'], 'mp3')

    def test_color_scheme(self):
        self.assertEqual(self.conf['COLOR_SCHEME'], 'light')

    def test_empty_string_value(self):
        self.assertEqual(self.conf['BIRDWEATHER_ID'], '')

    def test_empty_url_value(self):
        self.assertEqual(self.conf['HEARTBEAT_URL'], '')


# ---------------------------------------------------------------------------
# Numeric type coercion via getint / getfloat
# ---------------------------------------------------------------------------

class TestNumericCoercion(ConfigTestCase):

    def test_recording_length_as_int(self):
        self.assertEqual(self.conf.getint('RECORDING_LENGTH'), 15)

    def test_extraction_length_as_int(self):
        self.assertEqual(self.conf.getint('EXTRACTION_LENGTH'), 6)

    def test_confidence_as_float(self):
        self.assertAlmostEqual(self.conf.getfloat('CONFIDENCE'), 0.7)

    def test_sensitivity_as_float(self):
        self.assertAlmostEqual(self.conf.getfloat('SENSITIVITY'), 1.25)

    def test_overlap_as_float(self):
        self.assertAlmostEqual(self.conf.getfloat('OVERLAP'), 0.0)

    def test_latitude_as_float(self):
        self.assertAlmostEqual(self.conf.getfloat('LATITUDE'), 42.3601)

    def test_longitude_as_float_negative(self):
        self.assertAlmostEqual(self.conf.getfloat('LONGITUDE'), -71.0589)

    def test_sf_thresh_as_float(self):
        self.assertAlmostEqual(self.conf.getfloat('SF_THRESH'), 0.003)

    def test_privacy_threshold_as_int(self):
        self.assertEqual(self.conf.getint('PRIVACY_THRESHOLD'), 0)


# ---------------------------------------------------------------------------
# Boolean-like flags (stored as "0" / "1" strings)
# ---------------------------------------------------------------------------

class TestBooleanLikeFlags(ConfigTestCase):

    def test_raw_spectrogram_off_is_falsy(self):
        self.assertFalse(int(self.conf['RAW_SPECTROGRAM']))

    def test_raw_spectrogram_on_is_truthy(self):
        path = make_conf(FULL_CONF.replace('RAW_SPECTROGRAM="0"', 'RAW_SPECTROGRAM="1"'))
        try:
            helpers_module._settings = None
            conf = _load_settings(path)
            self.assertTrue(int(conf['RAW_SPECTROGRAM']))
        finally:
            os.unlink(path)
            helpers_module._settings = None

    def test_color_scheme_dark_is_accessible(self):
        path = make_conf(FULL_CONF.replace('COLOR_SCHEME="light"', 'COLOR_SCHEME="dark"'))
        try:
            helpers_module._settings = None
            conf = _load_settings(path)
            self.assertEqual(conf['COLOR_SCHEME'], 'dark')
        finally:
            os.unlink(path)
            helpers_module._settings = None


# ---------------------------------------------------------------------------
# Conditional logic driven by config (birdweather / heartbeat guards)
# ---------------------------------------------------------------------------

class TestConfigDrivenGuards(unittest.TestCase):
    """Verify that empty BIRDWEATHER_ID causes bird_weather() to return early."""

    def setUp(self):
        for _mod in ('apprise', 'soundfile', 'requests'):
            sys.modules.setdefault(_mod, MagicMock())
        from scripts.utils import reporting as rm
        self.rm = rm

    def test_bird_weather_returns_early_when_id_empty(self):
        from tests.helpers import Settings
        settings = Settings.with_defaults()
        settings.update({'BIRDWEATHER_ID': ''})

        from unittest.mock import patch
        with patch.object(self.rm, 'get_settings', return_value=settings), \
             patch.object(self.rm, 'soundfile') as mock_sf:
            self.rm.bird_weather(MagicMock(), [MagicMock()])

        mock_sf.read.assert_not_called()

    def test_heartbeat_skipped_when_url_empty(self):
        from tests.helpers import Settings
        settings = Settings.with_defaults()
        settings.update({'HEARTBEAT_URL': ''})

        from unittest.mock import patch
        mock_requests = MagicMock()
        with patch.object(self.rm, 'get_settings', return_value=settings), \
             patch.object(self.rm, 'requests', mock_requests):
            self.rm.heartbeat()

        mock_requests.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
