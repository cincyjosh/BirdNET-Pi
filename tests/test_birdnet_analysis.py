"""
Functional tests for scripts/birdnet_analysis.py.

Heavy dependencies (inotify, TFLite, librosa, apprise) are stubbed so
tests run without a Raspberry Pi, audio files, or ML models.
"""
import os
import sys
import tempfile
import unittest
from queue import Queue
from unittest.mock import MagicMock, patch, call

# Stub modules that are unavailable on the dev machine
for _mod in ('inotify', 'inotify.adapters', 'inotify.constants',
             'apprise', 'soundfile', 'requests', 'librosa',
             'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
             'tflite_runtime', 'tflite_runtime.interpreter'):
    sys.modules.setdefault(_mod, MagicMock())

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, _SCRIPTS_DIR)
import birdnet_analysis as ba  # noqa: E402
sys.path.pop(0)


# ---------------------------------------------------------------------------
# sig_handler
# ---------------------------------------------------------------------------

class TestSigHandler(unittest.TestCase):

    def setUp(self):
        ba.shutdown = False

    def tearDown(self):
        ba.shutdown = False

    def test_sets_shutdown_flag(self):
        ba.sig_handler(2, None)
        self.assertTrue(ba.shutdown)

    def test_sets_shutdown_for_sigterm(self):
        ba.sig_handler(15, None)
        self.assertTrue(ba.shutdown)


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------

class TestProcessFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue = Queue()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        # drain the queue
        while not self.queue.empty():
            self.queue.get()
            self.queue.task_done()

    def _wav(self, name='2024-06-15-birdnet-07:30:00.wav', content=b'\x00' * 100):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'wb') as f:
            f.write(content)
        return path

    def test_zero_byte_file_is_deleted(self):
        path = self._wav(content=b'')
        with patch.object(ba, 'ANALYZING_NOW', os.path.join(self.tmpdir, 'now.txt')):
            ba.process_file(path, self.queue)
        self.assertFalse(os.path.exists(path))

    def test_zero_byte_file_not_queued(self):
        path = self._wav(content=b'')
        with patch.object(ba, 'ANALYZING_NOW', os.path.join(self.tmpdir, 'now.txt')):
            ba.process_file(path, self.queue)
        self.assertTrue(self.queue.empty())

    def test_valid_file_writes_analyzing_now(self):
        path = self._wav()
        analyzing_now = os.path.join(self.tmpdir, 'analyzing_now.txt')
        fake_detections = [MagicMock()]

        with patch.object(ba, 'ANALYZING_NOW', analyzing_now), \
             patch.object(ba, 'run_analysis', return_value=fake_detections), \
             patch.object(ba, 'ParseFileName', return_value=MagicMock()):
            ba.process_file(path, self.queue)

        self.assertTrue(os.path.exists(analyzing_now))
        with open(analyzing_now) as f:
            self.assertEqual(f.read(), path)

    def test_valid_file_puts_result_on_queue(self):
        path = self._wav()
        analyzing_now = os.path.join(self.tmpdir, 'analyzing_now.txt')
        fake_detections = [MagicMock()]
        fake_file = MagicMock()

        with patch.object(ba, 'ANALYZING_NOW', analyzing_now), \
             patch.object(ba, 'run_analysis', return_value=fake_detections), \
             patch.object(ba, 'ParseFileName', return_value=fake_file):
            ba.process_file(path, self.queue)

        self.assertFalse(self.queue.empty())
        item = self.queue.get()
        self.assertEqual(item, (fake_file, fake_detections))

    def test_exception_during_analysis_does_not_crash(self):
        path = self._wav()
        analyzing_now = os.path.join(self.tmpdir, 'analyzing_now.txt')

        with patch.object(ba, 'ANALYZING_NOW', analyzing_now), \
             patch.object(ba, 'run_analysis', side_effect=RuntimeError('boom')), \
             patch.object(ba, 'ParseFileName', return_value=MagicMock()):
            # Should not raise
            ba.process_file(path, self.queue)

        self.assertTrue(self.queue.empty())


# ---------------------------------------------------------------------------
# handle_reporting_queue
# ---------------------------------------------------------------------------

class TestHandleReportingQueue(unittest.TestCase):

    # Patches applied to every test in this class
    _ALWAYS_PATCH = [
        ('update_json_file', {}),
        ('extract_detection', {'return_value': '/tmp/det.mp3'}),
        ('summary', {'return_value': 'sci;common;0.85'}),
        ('write_to_file', {}),
        ('write_to_db', {}),
        ('apprise', {}),
        ('bird_weather', {}),
        ('heartbeat', {}),
    ]

    def setUp(self):
        self._patchers = []
        for name, kwargs in self._ALWAYS_PATCH:
            p = patch.object(ba, name, **kwargs)
            setattr(self, f'mock_{name}', p.start())
            self._patchers.append(p)
        self._rm_patcher = patch.object(ba.os, 'remove')
        self.mock_remove = self._rm_patcher.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._rm_patcher.stop()

    def _run_queue(self, items):
        """Run handle_reporting_queue with the given items followed by None sentinel."""
        q = Queue()
        for item in items:
            q.put(item)
        q.put(None)  # sentinel
        ba.handle_reporting_queue(q)
        return q

    def _make_item(self, n_detections=1):
        file_mock = MagicMock()
        detections = [MagicMock() for _ in range(n_detections)]
        return file_mock, detections

    def test_stops_on_none_sentinel(self):
        # If it doesn't stop, the test would hang
        q = self._run_queue([])
        self.assertTrue(q.empty())

    def test_processes_single_item(self):
        file_mock, dets = self._make_item(n_detections=2)
        self._run_queue([(file_mock, dets)])
        self.mock_update_json_file.assert_called_once_with(file_mock, dets)

    def test_calls_reporting_steps_for_each_detection(self):
        file_mock, dets = self._make_item(n_detections=2)
        self._run_queue([(file_mock, dets)])
        self.assertEqual(self.mock_extract_detection.call_count, 2)
        self.assertEqual(self.mock_write_to_file.call_count, 2)
        self.assertEqual(self.mock_write_to_db.call_count, 2)

    def test_calls_apprise_once_per_item(self):
        file_mock, dets = self._make_item(n_detections=3)
        self._run_queue([(file_mock, dets)])
        self.mock_apprise.assert_called_once_with(file_mock, dets)

    def test_removes_source_file_after_processing(self):
        file_mock = MagicMock()
        file_mock.file_name = '/tmp/source.wav'
        self._run_queue([(file_mock, [])])
        self.mock_remove.assert_called_once_with('/tmp/source.wav')

    def test_exception_in_handler_does_not_stop_queue(self):
        """An error processing one item should not prevent the next from running."""
        file_mock1, dets1 = self._make_item()
        file_mock2, dets2 = self._make_item()

        heartbeat_calls = []
        self.mock_heartbeat.side_effect = lambda: heartbeat_calls.append(1)
        self.mock_update_json_file.side_effect = [RuntimeError('oops'), None]

        self._run_queue([(file_mock1, dets1), (file_mock2, dets2)])

        # Second item's heartbeat should have been called despite first item failing
        self.assertEqual(heartbeat_calls, [1])


if __name__ == '__main__':
    unittest.main()
