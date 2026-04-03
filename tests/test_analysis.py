import os
import unittest
from unittest.mock import patch

from scripts.utils.analysis import run_analysis
from scripts.utils.classes import ParseFileName
from tests.helpers import TESTDATA, Settings
from scripts.utils.analysis import filter_humans


class TestRunAnalysis(unittest.TestCase):

    def setUp(self):
        source = os.path.join(TESTDATA, 'Pica pica_30s.wav')
        self.test_file = os.path.join(TESTDATA, '2024-02-24-birdnet-16:19:37.wav')
        if os.path.exists(self.test_file):
            os.unlink(self.test_file)
        os.symlink(source, self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.unlink(self.test_file)

    @patch('scripts.utils.helpers._load_settings')
    @patch('scripts.utils.analysis.loadCustomSpeciesList')
    def test_run_analysis(self, mock_loadCustomSpeciesList, mock_load_settings):
        # Mock the settings and species list
        mock_load_settings.return_value = Settings.with_defaults()
        mock_loadCustomSpeciesList.return_value = []

        # Test file
        test_file = ParseFileName(self.test_file)

        # Run the analysis
        detections = run_analysis(test_file)

        # Assertions: correct species detected with high confidence (exact values vary by platform/tf version)
        self.assertGreater(len(detections), 0)
        for det in detections:
            self.assertEqual(det.scientific_name, 'Pica pica')
            self.assertGreater(det.confidence, 0.8)


class TestFilterHumans(unittest.TestCase):

    @patch('scripts.utils.helpers._load_settings')
    def test_filter_humans_no_human(self, mock_load_settings):
        mock_load_settings.return_value = Settings.with_defaults()

        # Input detections without humans
        detections = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_C', 0.7), ('Bird_D', 0.6)]
        ]

        # Expected output
        expected = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_C', 0.7), ('Bird_D', 0.6)]
        ]

        # Run filter_humans
        result = filter_humans(detections)

        # Assertions
        self.assertEqual(result, expected)

    @patch('scripts.utils.helpers._load_settings')
    def test_filter_empty(self, mock_load_settings):
        mock_load_settings.return_value = Settings.with_defaults()

        # Input detections without humans
        detections = []

        # Expected output
        expected = []

        # Run filter_humans
        result = filter_humans(detections)

        # Assertions
        self.assertEqual(result, expected)

    @patch('scripts.utils.helpers._load_settings')
    def test_filter_humans_with_human(self, mock_load_settings):
        mock_load_settings.return_value = Settings.with_defaults()

        # Input detections with humans
        detections = [
            [('Human_Human', 0.95), ('Bird_A', 0.8)],
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_C', 0.9), ('Bird_D', 0.8)],
            [('Bird_B', 0.7), ('Human vocal_Human vocal', 0.9)]
        ]

        # Expected output
        expected = [
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)]
        ]

        # Run filter_humans
        result = filter_humans(detections)

        # Assertions
        self.assertEqual(result, expected)

    @patch('scripts.utils.helpers._load_settings')
    def test_filter_humans_with_human_neighbour(self, mock_load_settings):
        mock_load_settings.return_value = Settings.with_defaults()

        # Input detections with human neighbours
        detections = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_D', 0.9), ('Bird_E', 0.8)],
            [('Human_Human', 0.95), ('Bird_C', 0.7)],
            [('Bird_F', 0.6), ('Bird_G', 0.5)]
        ]

        # Expected output
        expected = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)]
        ]

        # Run filter_humans
        result = filter_humans(detections)

        # Assertions
        self.assertEqual(result, expected)

    @patch('scripts.utils.helpers._load_settings')
    def test_filter_humans_with_deep_human(self, mock_load_settings):
        mock_load_settings.return_value = Settings.with_defaults()

        # Input detections with human neighbours
        detections = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_D', 0.9), ('Bird_E', 0.8)],
            [('Bird_C', 0.7)] * 10 + [('Human_Human', 0.95)],
            [('Bird_F', 0.6), ('Bird_G', 0.5)]
        ]

        # Expected output
        expected = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_D', 0.9), ('Bird_E', 0.8)],
            [('Bird_C', 0.7)] * 10,
            [('Bird_F', 0.6), ('Bird_G', 0.5)]
        ]

        # Run filter_humans
        result = filter_humans(detections)

        # Assertions
        self.assertEqual(result, expected)

    @patch('scripts.utils.helpers._load_settings')
    def test_filter_humans_with_human_deep(self, mock_load_settings):
        settings = Settings.with_defaults()
        settings['PRIVACY_THRESHOLD'] = 1
        mock_load_settings.return_value = settings

        # Input detections with human neighbours
        detections = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Bird_D', 0.9), ('Bird_E', 0.8)],
            [('Bird_C', 0.7)] * 10 + [('Human_Human', 0.95)],
            [('Bird_F', 0.6), ('Bird_G', 0.5)]
        ]

        # Expected output
        expected = [
            [('Bird_A', 0.9), ('Bird_B', 0.8)],
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)],
            [('Human_Human', 0.0)]
        ]

        # Run filter_humans
        result = filter_humans(detections)

        # Assertions
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
