# SPDX-License-Identifier: GPL-3.0-or-later
import pathlib
import runpy
import unittest
m=runpy.run_path(str((pathlib.Path(__file__).resolve().parents[1] / "transport" / "local-mux-sequence.py")))
class Tests(unittest.TestCase):
    def test_wire_wrap(self):
        self.assertEqual(m["wire_sequence"](2**32+17),17)
    def test_ack_across_wrap(self):
        self.assertEqual(m["unwrap_ack"](19,2**32-10,2**32+30),2**32+19)
    def test_duplicate(self):
        self.assertEqual(m["unwrap_ack"](7,2**32+7,2**32+40),2**32+7)
    def test_reject_future_and_stale(self):
        for wire,previous,sent in ((41,2**32+7,2**32+40),(6,2**32+7,2**32+40),(0,0,2**32)):
            with self.assertRaises(ValueError):m["unwrap_ack"](wire,previous,sent)
    def test_credit_delayed_ack_and_fin_across_wrap(self):
        credit=runpy.run_path(str((pathlib.Path(__file__).resolve().parents[1] / "transport" / "local-mux-credit.py")))["allowance"]
        sent=acknowledged=2**32-32768
        initial=sent
        # Same 16KiB reads and 1MiB outstanding cap as the real controller.
        while credit(sent,acknowledged):
            sent+=credit(sent,acknowledged)
        self.assertEqual(sent-initial,1048576)
        self.assertEqual(credit(sent,acknowledged),0)
        acknowledged=m["unwrap_ack"](m["wire_sequence"](sent-16384),acknowledged,sent)
        self.assertGreater(acknowledged,2**32)
        self.assertEqual(credit(sent,acknowledged),16384)
        self.assertEqual(m["unwrap_ack"](m["wire_sequence"](acknowledged),acknowledged,sent),acknowledged)
        with self.assertRaises(ValueError):
            m["unwrap_ack"](m["wire_sequence"](acknowledged-1),acknowledged,sent)
        fin_end=sent+1
        self.assertEqual(m["unwrap_ack"](m["wire_sequence"](fin_end),acknowledged,fin_end),fin_end)

    def test_full_image_stream(self):
        sent=previous=1
        while sent<14289993728:
            sent+=1048576
            previous=m["unwrap_ack"](m["wire_sequence"](sent),previous,sent)
        self.assertEqual(previous,sent)
if __name__=="__main__":unittest.main()
