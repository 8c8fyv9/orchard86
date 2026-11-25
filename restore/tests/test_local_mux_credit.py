# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline regression coverage; never opens or changes running guest state."""
import pathlib
import random
import runpy
import unittest

allowance = runpy.run_path(str((pathlib.Path(__file__).resolve().parents[1] / "transport" / "local-mux-credit.py")))["allowance"]
LIMIT = 1048576

class Tests(unittest.TestCase):
    def test_large_oob_without_intermediate_ack(self):
        sent = 0
        while sent < 500807:
            size = min(allowance(sent, 0), 500807 - sent)
            self.assertGreater(size, 0)
            sent += size
        self.assertEqual(sent, 500807)

    def test_credit_boundary_and_resume(self):
        for remaining in (0, 1, 16383, 16384, 16385, LIMIT):
            self.assertEqual(allowance(LIMIT - remaining, 0), min(16384, remaining))
        self.assertEqual(allowance(LIMIT, 16384), 16384)
        self.assertEqual(allowance(LIMIT + 1, 0), 0)

    def test_invalid_order(self):
        for sent, ack in ((-1, 0), (0, -1), (1, 2)):
            with self.assertRaises(ValueError):
                allowance(sent, ack)

    def test_stream_credit_invariants(self):
        rng = random.Random(81)
        sent = ack = 1  # established stream after SYN
        for _ in range(20000):
            if rng.randrange(3) == 0:
                ack += rng.randrange(sent - ack + 1)
            credit = allowance(sent, ack)
            self.assertTrue(0 <= credit <= 16384)
            self.assertLessEqual(sent - ack + credit, LIMIT)
            sent += rng.randrange(credit + 1)
        self.assertGreater(sent, 10 * LIMIT)

    def test_absolute_counters_above_wire_wrap(self):
        # Primitive expects unwrapped counters; wire unwrap remains caller's duty.
        self.assertEqual(allowance(2**32 + 500807, 2**32), 16384)

if __name__ == "__main__":
    unittest.main()
