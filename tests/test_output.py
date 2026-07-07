"""Unit tests for output transaction and stale file recovery helpers.

Focuses on cleanup behavior, atomic output assumptions, and filesystem safety
for crash-recovery scenarios.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from capture_shared.output import recover_stale_outputs


class OutputRecoveryTests(unittest.TestCase):
    def test_recovery_removes_stale_temporary_and_empty_reservation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            temporary = output_dir / ".frame_000001.token.tmp.jpg"
            reservation = output_dir / "frame_000001.jpg"
            completed = output_dir / "frame_000002.jpg"
            temporary.write_bytes(b"partial")
            reservation.touch()
            completed.write_bytes(b"complete")
            old = time.time() - 7200
            for path in (temporary, reservation, completed):
                os.utime(path, (old, old))

            removed = recover_stale_outputs(output_dir, older_than_seconds=3600)

            self.assertEqual(2, removed)
            self.assertFalse(temporary.exists())
            self.assertFalse(reservation.exists())
            self.assertTrue(completed.exists())


if __name__ == "__main__":
    unittest.main()
