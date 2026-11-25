#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import runpy
import socket
import struct
import unittest
from pathlib import Path
p = runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / "local-usbmux-control.py")))

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair()
        self.a.settimeout(1); self.b.settimeout(1)
        self.inventory = p["GuestInventory"](serial="synthetic-unit-test", product_id=1)
    def tearDown(self):
        self.a.close(); self.b.close()
    def reply(self):
        return p["receive"](self.b, request=False)
    def test_inventory_and_events(self):
        self.assertEqual(self.inventory.handle(self.a, 4, {"MessageType":"ListDevices"}), "close")
        self.assertEqual(self.reply()[1]["DeviceList"][0]["DeviceID"], 1)
        self.assertEqual(self.inventory.handle(self.a, 5, {"MessageType":"Listen"}), "listen")
        self.assertEqual(self.reply()[1]["Number"], 0)
        self.assertEqual(self.reply()[1]["MessageType"], "Attached")
        self.inventory.detach([self.a])
        self.assertEqual(self.reply()[1]["MessageType"], "Detached")
        self.inventory.handle(self.a, 6, {"MessageType":"ListDevices"})
        self.assertEqual(self.reply()[1]["DeviceList"], [])
    def test_connect_needs_real_handoff(self):
        request = {"MessageType":"Connect", "DeviceID":1, "PortNumber":socket.htons(62078)}
        self.assertEqual(self.inventory.handle(self.a, 1, request), "connect")
        self.b.setblocking(False)
        with self.assertRaises(BlockingIOError): self.b.recv(1)
        self.b.settimeout(1)
        self.inventory.live = False
        self.assertEqual(self.inventory.handle(self.a, 1, request), "close")
        self.assertEqual(self.reply()[1]["Number"], 3)
    def test_asr_allowlist(self):
        inventory = p["GuestInventory"](serial="unit", product_id=1, allowed_ports=(62078,12345))
        for port, expected in ((12345,"connect"),(22,"close")):
            request={"MessageType":"Connect","DeviceID":1,"PortNumber":socket.htons(port)}
            self.assertEqual(inventory.handle(self.a,1,request),expected)
        self.assertEqual(self.reply()[1]["Number"],3)
        with self.assertRaises(ValueError):
            p["GuestInventory"](serial="unit",product_id=1,allowed_ports=(True,))
    def test_dynamic_ports_are_scoped_to_live_device(self):
        inventory = p["GuestInventory"](serial="unit", product_id=1, allowed_ports=None)
        for port in (1, 49152, 65535):
            request = {"MessageType":"Connect", "DeviceID":1, "PortNumber":socket.htons(port)}
            self.assertEqual(inventory.handle(self.a, 2, request), "connect")
        self.b.setblocking(False)
        with self.assertRaises(BlockingIOError): self.b.recv(1)
        self.b.settimeout(1)
        for device, port in ((2, 49152), (1, 0), (True, 49152)):
            request = {"MessageType":"Connect", "DeviceID":device, "PortNumber":socket.htons(port)}
            self.assertEqual(inventory.handle(self.a, 2, request), "close")
            self.assertEqual(self.reply()[1]["Number"], 3)
        inventory.live = False
        self.assertEqual(inventory.handle(self.a, 2, {"MessageType":"Connect", "DeviceID":1,
                         "PortNumber":socket.htons(49152)}), "close")
        self.assertEqual(self.reply()[1]["Number"], 3)

    def test_invalid_identity(self):
        for serial in ("", "bad\x00value", "a"*256):
            with self.assertRaises(ValueError):
                p["GuestInventory"](serial=serial, product_id=1)
    def test_bounds(self):
        self.a.sendall(struct.pack("<4I", 65537,1,8,1))
        with self.assertRaises(ValueError): p["receive"](self.b)
    def test_request_roundtrip(self):
        p["send"](self.a, 31, {"MessageType":"ListDevices"})
        self.assertEqual(self.reply(), (31, {"MessageType":"ListDevices"}))

if __name__ == "__main__": unittest.main()
