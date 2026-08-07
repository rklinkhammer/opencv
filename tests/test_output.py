"""Unit tests for output transaction and stale file recovery helpers.

Focuses on cleanup behavior, atomic output assumptions, and filesystem safety
for crash-recovery scenarios.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Barrier, Lock, Thread

from capture_shared.output import recover_stale_outputs, reserve_unique_path


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

    def test_concurrent_reservations_never_choose_the_same_path(self):
        worker_count = 16
        start = Barrier(worker_count)
        paths = []
        errors = []
        result_lock = Lock()

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)

            def reserve() -> None:
                start.wait()
                try:
                    path = reserve_unique_path(output_dir, "frame", "jpg")
                    with result_lock:
                        paths.append(path)
                except Exception as exc:
                    with result_lock:
                        errors.append(exc)

            threads = [Thread(target=reserve) for _ in range(worker_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual([], errors)
            self.assertEqual(worker_count, len(paths))
            self.assertEqual(worker_count, len(set(paths)))
            self.assertTrue(all(path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
