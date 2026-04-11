"""
Functional tests for language/label utilities in scripts/utils/helpers.py:
  get_language, save_language, get_model_labels, set_label_file
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

for _mod in ('apprise', 'soundfile', 'requests', 'librosa',
             'inotify', 'inotify.adapters', 'inotify.constants'):
    sys.modules.setdefault(_mod, MagicMock())

import scripts.utils.helpers as helpers_module  # noqa: E402
from scripts.utils.helpers import (  # noqa: E402
    get_language, get_model_labels, save_language,
)

# Use the real English label file bundled with the repo
_REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
_EN_LABELS = os.path.join(_REPO_ROOT, 'model/l18n/labels_en.json')
_MODEL_LABELS = os.path.join(_REPO_ROOT, 'model/BirdNET_GLOBAL_6K_V2.4_Model_FP16_Labels.txt')


# ---------------------------------------------------------------------------
# get_language
# ---------------------------------------------------------------------------

class TestGetLanguage(unittest.TestCase):

    def setUp(self):
        helpers_module._settings = None

    def tearDown(self):
        helpers_module._settings = None

    def test_returns_dict(self):
        result = get_language('en')
        self.assertIsInstance(result, dict)

    def test_dict_is_nonempty(self):
        result = get_language('en')
        self.assertGreater(len(result), 0)

    def test_keys_are_scientific_names(self):
        result = get_language('en')
        # Scientific names contain a space between genus and species
        sample_key = next(iter(result))
        self.assertIn(' ', sample_key)

    def test_values_are_common_names(self):
        result = get_language('en')
        self.assertIsInstance(next(iter(result.values())), str)

    def test_known_species_english(self):
        result = get_language('en')
        # American Robin is in every model version
        self.assertIn('Turdus migratorius', result)
        self.assertEqual(result['Turdus migratorius'], 'American Robin')

    def test_uses_settings_lang_when_none_given(self):
        from tests.helpers import Settings
        settings = Settings.with_defaults()   # DATABASE_LANG = 'en'
        helpers_module._settings = None
        with patch.object(helpers_module, 'get_settings', return_value=settings):
            result = get_language()
        self.assertIn('Turdus migratorius', result)

    def test_german_labels_load(self):
        result = get_language('de')
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)


# ---------------------------------------------------------------------------
# save_language
# ---------------------------------------------------------------------------

class TestSaveLanguage(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _tmp_model_path(self):
        l18n = os.path.join(self.tmpdir, 'l18n')
        os.makedirs(l18n, exist_ok=True)
        return self.tmpdir

    def test_writes_json_file(self):
        labels = {'Turdus migratorius': 'American Robin', 'Cyanocitta cristata': 'Blue Jay'}
        with patch.object(helpers_module, 'MODEL_PATH', self._tmp_model_path()):
            save_language(labels, 'test')
        out = os.path.join(self.tmpdir, 'l18n', 'labels_test.json')
        self.assertTrue(os.path.exists(out))

    def test_written_json_is_valid(self):
        labels = {'Turdus migratorius': 'American Robin'}
        with patch.object(helpers_module, 'MODEL_PATH', self._tmp_model_path()):
            save_language(labels, 'test')
        out = os.path.join(self.tmpdir, 'l18n', 'labels_test.json')
        with open(out) as f:
            data = json.load(f)
        self.assertEqual(data, {'Turdus migratorius': 'American Robin'})

    def test_output_is_sorted_alphabetically(self):
        labels = {'Zenaida macroura': 'Mourning Dove', 'Aix sponsa': 'Wood Duck'}
        with patch.object(helpers_module, 'MODEL_PATH', self._tmp_model_path()):
            save_language(labels, 'test')
        out = os.path.join(self.tmpdir, 'l18n', 'labels_test.json')
        with open(out) as f:
            data = json.load(f)
        keys = list(data.keys())
        self.assertEqual(keys, sorted(keys))

    def test_roundtrip(self):
        """save then load gives back the same dict."""
        original = {'Turdus migratorius': 'American Robin', 'Cyanocitta cristata': 'Blue Jay'}
        model_path = self._tmp_model_path()
        with patch.object(helpers_module, 'MODEL_PATH', model_path):
            save_language(original, 'roundtrip')
            loaded = get_language('roundtrip')
        self.assertEqual(loaded, original)

    def test_non_ascii_preserved(self):
        labels = {'Luscinia megarhynchos': 'Nachtigall'}
        with patch.object(helpers_module, 'MODEL_PATH', self._tmp_model_path()):
            save_language(labels, 'test')
        out = os.path.join(self.tmpdir, 'l18n', 'labels_test.json')
        with open(out, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Nachtigall', content)


# ---------------------------------------------------------------------------
# get_model_labels
# ---------------------------------------------------------------------------

class TestGetModelLabels(unittest.TestCase):

    def setUp(self):
        helpers_module._settings = None

    def tearDown(self):
        helpers_module._settings = None

    def test_returns_list(self):
        result = get_model_labels('BirdNET_GLOBAL_6K_V2.4_Model_FP16')
        self.assertIsInstance(result, list)

    def test_list_is_nonempty(self):
        result = get_model_labels('BirdNET_GLOBAL_6K_V2.4_Model_FP16')
        self.assertGreater(len(result), 0)

    def test_labels_are_strings(self):
        result = get_model_labels('BirdNET_GLOBAL_6K_V2.4_Model_FP16')
        self.assertTrue(all(isinstance(label, str) for label in result))

    def test_no_trailing_newlines(self):
        result = get_model_labels('BirdNET_GLOBAL_6K_V2.4_Model_FP16')
        self.assertTrue(all('\n' not in label for label in result))

    def test_uses_settings_model_when_none_given(self):
        from tests.helpers import Settings
        settings = Settings.with_defaults()  # MODEL = BirdNET_GLOBAL_6K_V2.4_Model_FP16
        with patch.object(helpers_module, 'get_settings', return_value=settings):
            result = get_model_labels()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_bidirectional_suffix_stripped(self):
        """Labels in 'CommonName_Scientific Name' format get suffix stripped."""
        # Exactly one underscore triggers re.sub(r'_.+$', '') which removes
        # everything from the first underscore onwards.
        fake_labels = ['American Robin_Turdus migratorius\n',
                       'Blue Jay_Cyanocitta cristata\n']
        tmpdir = tempfile.mkdtemp()
        try:
            label_file = os.path.join(tmpdir, 'FakeModel_Labels.txt')
            with open(label_file, 'w') as f:
                f.writelines(fake_labels)
            with patch.object(helpers_module, 'MODEL_PATH', tmpdir):
                result = get_model_labels('FakeModel')
            self.assertEqual(result, ['American Robin', 'Blue Jay'])
        finally:
            import shutil
            shutil.rmtree(tmpdir)


if __name__ == '__main__':
    unittest.main()
