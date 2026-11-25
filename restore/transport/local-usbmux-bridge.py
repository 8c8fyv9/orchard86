#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private mux control with real connector; opaque stream relay, no plist edits."""
import os
from pathlib import Path
import runpy
import socket
import threading
import traceback
api = runpy.run_path(str(Path(__file__).with_name("local-usbmux-control.py")))
relay = runpy.run_path(str(Path(__file__).with_name("local-stream-relay.py")))["relay"]

class Bridge:
    def __init__(self, inventory, connector, *, stop, deadline, transform=None):
        self.inventory = inventory
        self.connector = connector
        self.stop = stop
        self.deadline = deadline
        self.transform = transform
        self.errors = []

    def handle(self, connection):
        guest = None
        request = {}
        try:
            tag, request = api["receive"](connection)
            action = self.inventory.handle(connection, tag, request)
            if action == "listen":
                connection.settimeout(1)
                while not self.stop.is_set():
                    try:
                        if not connection.recv(1):break
                    except socket.timeout:continue
            elif action == "connect":
                # Connector must finish the guest's SYN/SYN-ACK before returning.
                port = socket.ntohs(request["PortNumber"])
                guest = self.connector(port)
                if not isinstance(guest, socket.socket):
                    raise ConnectionError("connector did not return a live stream")
                api["send"](connection, tag, {"MessageType":"Result", "Number":0})
                relay(
                    connection,
                    guest,
                    deadline=self.deadline,
                    stop=self.stop,
                    transform=self.transform if port == 62078 else None,
                )
        except Exception as error:
            port = request.get("PortNumber")
            port = socket.ntohs(port) if isinstance(port, int) else None
            self.errors.append(f"{type(error).__name__}: {error}; guest_port={port}; " + traceback.format_exc())
        finally:
            if guest is not None:guest.close()
            connection.close()

    def serve(self, path):
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen()
            server.settimeout(1)
            while not self.stop.is_set():
                try:connection, _ = server.accept()
                except socket.timeout:continue
                threading.Thread(target=self.handle, args=(connection,), daemon=True).start()
