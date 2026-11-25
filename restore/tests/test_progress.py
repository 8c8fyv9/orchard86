# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from progress import scan


class ProgressTests(unittest.TestCase):
    def test_unqualified_percent_and_dispatch_are_not_completion(self):
        result = scan(['Checkpoint completed id: 0x658 (format_media) result=0',
                       'Checkpoint completed id: 0x65B (restore_system_image) result=0',
                       'Sending filesystem now...', '100.0%',
                       'Checkpoint started id: 0x6B4 (await_system_image_invert_retry)'], [])
        self.assertTrue(result['media_format_completed'])
        self.assertTrue(result['asr_send_started'])
        self.assertTrue(result['invert_wait_started'])
        self.assertFalse(result['asr_host_send_finished'])
        self.assertFalse(result['native_success_marker'])

    def test_host_finished_does_not_override_failed_seal(self):
        result = scan([
            'Checkpoint completed id: 0x68B (seal_system_volume) result=0',
            'Checkpoint completed id: 0x68B (seal_system_volume) result=-1',
            'Checkpoint completed id: 0x669 (create_system_snapshot) result=0',
            'Status: Restore Finished',
        ], [])
        self.assertFalse(result['seal_checkpoint_ok'])
        self.assertTrue(result['snapshot_checkpoint_ok'])
        self.assertTrue(result['host_restore_finished_marker'])
        self.assertFalse(result['native_success_marker'])
        self.assertEqual(result['checkpoint_errors']['seal_system_volume'], -1)

    def test_native_transfer_samples_match_exact_image_size(self):
        result = scan([], [
            'Transfer: Received 10 bytes in 0.02 seconds, 0.00 MB/s from host',
            'Transfer: Received 200 bytes in 2.00 seconds, 0.01 MB/s from host (bus info)',
            'Transfer: Verified 200 bytes in 0.10 seconds, 0.02 MB/s from disk',
            'prefix Transfer: Wrote 200 bytes in 0.10 seconds, 0.02 MB/s to disk',
        ], image_bytes=200)
        samples = result['image_transfer_samples']
        self.assertEqual([sample['operation'] for sample in samples], ['Received', 'Verified'])
        self.assertEqual(samples[0]['guest_seconds'], 2.0)
        self.assertFalse(result['native_success_marker'])

    def test_host_completion_can_share_progress_line(self):
        self.assertTrue(scan(['[==== ]  99.0%Done sending filesystem'], [])['asr_host_send_finished'])
        self.assertFalse(scan(['error: Done sending filesystem'], [])['asr_host_send_finished'])

    def test_exact_native_markers(self):
        for text in ('restore-outcome = initial_engine_success', 'restore-outcome = success (copied)'):
            self.assertFalse(scan([], [text])['native_success_marker'])
        result = scan(['Done sending filesystem'], ['restore-outcome = success',
                      'System ARV snapshot successfully created.', 'ApplePSCI - system reset'])
        for key in ('asr_host_send_finished', 'native_success_marker', 'snapshot_marker', 'psci_marker'):
            self.assertTrue(result[key])
