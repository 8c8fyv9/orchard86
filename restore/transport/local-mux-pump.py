#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opaque multi-stream mux pump after actual USB version negotiation."""
from collections import deque
from pathlib import Path
import queue
import math
import runpy
import socket
import struct
import sys
import threading

base = Path(__file__).parent
State = runpy.run_path(str(base/'local-mux-stream-state.py'))['State']
ReceiveBuffer = runpy.run_path(str(base/'local-stream-buffer.py'))['ReceiveBuffer']
parse = runpy.run_path(str(base/'local-mux-packet.py'))['parse']
sequence_api = runpy.run_path(str(base/'local-mux-sequence.py'))

class Pump:
    def __init__(self, transport, stop, *, poll_interval=.002):
        if not math.isfinite(poll_interval) or not 0 < poll_interval <= 1:
            raise ValueError("finite positive host poll interval <= 1 second required")
        self.poll_interval = poll_interval
        self.transport = transport
        self.stop = stop
        self.mux = State()
        self.usb_input = bytearray()
        self.control_messages = deque(maxlen=256)
        self.outgoing = deque([(2, bytes([7]))])
        self.out_busy = False
        self.in_pending = False
        self.requests = queue.Queue()
        self.connections = {}
        self.next_port = 49152

    def connect(self, port):
        app, wire = socket.socketpair()
        wire.setblocking(False)
        state = dict(port=port, socket=wire, ready=threading.Event(),
                     seq=0, ack=0, peer_ack=0, open=False, tx_fin=None,
                     rx=None, rx_shutdown=False, error=None, peer_window=0)
        self.requests.put(state)
        while not state['ready'].wait(.1):
            if self.stop.is_set():
                app.close()
                raise InterruptedError('mux pump stopped')
        if state['error']:
            app.close()
            raise ConnectionError(state['error'])
        return app

    def tcp(self, source, state, flags, payload=b''):
        header = struct.pack('!HHIIBBHHH',source,state['port'],state['seq']%2**32,
                             state['ack']%2**32,80,flags,512,0,0)
        self.outgoing.append((6, header + payload))

    def receive_usb(self, chunk):
        # Bulk USB completions may split/coalesce mux frames or carry a ZLP.
        self.usb_input.extend(chunk)
        while len(self.usb_input) >= 16:
            protocol, length, magic = struct.unpack_from('!III', self.usb_input)
            if protocol not in (1, 2, 6) or magic != 0xfaceface or not 16 <= length <= 65536:
                raise ValueError(f'invalid USB mux header: protocol={protocol} length={length} magic={magic:#x} buffered={len(self.usb_input)}')
            if len(self.usb_input) < length:
                return
            packet = bytes(self.usb_input[:length])
            del self.usb_input[:length]
            self.receive(packet)

    def receive(self, packet):
        protocol, payload = self.mux.receive(packet)
        if protocol == 1:
            # Device control diagnostics are session-wide logs, not disconnects.
            # Keep TCP RST/FIN and actual ASR errors authoritative per stream.
            self.control_messages.append(bytes(payload))
            print('guest mux control:', repr(payload), file=sys.stderr, flush=True)
            return
        if protocol != 6:return
        decoded = parse(packet)
        source = decoded['destination']
        state = self.connections[source]
        if decoded['source'] != state['port']:
            raise ValueError('guest port mismatch')
        flags = decoded['flags']
        state['peer_window'] = decoded['window'] << 8
        if flags & 4:
            state['error']='guest reset connection'
            state['open']=False
            state['socket'].close()
            state['ready'].set()
            return
        ack = decoded['acknowledgement']
        if ack is None:raise ValueError('guest stream lacks ACK')
        state['peer_ack'] = sequence_api['unwrap_ack'](ack,state['peer_ack'],
                                                       state['seq'] + (not state['open']))
        if flags & 2:
            if state['open'] or ack != 1:raise ValueError('invalid SYN-ACK')
            state.update(seq=1, ack=decoded['sequence']+1, open=True,
                         rx=ReceiveBuffer(sequence=decoded['sequence']+1))
            self.tcp(source,state,16)
            state['ready'].set()
            return
        payload=decoded['payload']
        if payload:
            # Accept only contiguous bytes; ACK already-consumed retransmissions.
            delta=(decoded['sequence']-state['ack'])%2**32
            if delta >= 2**31:
                overlap=2**32-delta
                payload=payload[min(overlap,len(payload)):]
            elif delta:
                self.tcp(source,state,16)
                return
            if payload:state['ack']=state['rx'].accept(state['ack'],payload)
        if flags & 1:
            fin=(decoded['sequence']+len(decoded['payload']))%2**32
            if fin == state['ack']%2**32:
                state['ack']=state['rx'].accept_fin(state['ack'])
            elif state['rx'].fin_sequence is None or fin != state['rx'].fin_sequence%2**32:
                raise ValueError('noncontiguous FIN')
        if decoded['payload'] or flags & 1:self.tcp(source,state,16)

    def tick(self):
        while True:
            try:state=self.requests.get_nowait()
            except queue.Empty:break
            if self.next_port > 65535:raise RuntimeError('source ports exhausted')
            source=self.next_port;self.next_port+=1
            self.connections[source]=state
            self.tcp(source,state,2)
        for source,state in self.connections.items():
            if not state['open']:continue
            rx=state['rx']
            rx.drain(state['socket'].send)
            if rx.eof_ready and not state['rx_shutdown']:
                state['socket'].shutdown(socket.SHUT_WR);state['rx_shutdown']=True
            if state['tx_fin'] is not None:continue
            credit=min(16384,max(0,state['peer_window']-(state['seq']-state['peer_ack'])))
            if not credit:continue
            try:chunk=state['socket'].recv(credit)
            except BlockingIOError:continue
            if chunk:
                self.tcp(source,state,16,chunk);state['seq']+=len(chunk)
            else:
                self.tcp(source,state,17);state['tx_fin']=state['seq'];state['seq']+=1
        while True:
            response=self.transport.receive()
            if response is None:break
            if response == bytes([1,1]):
                if not self.out_busy:raise ValueError('unexpected OUT completion')
                self.out_busy=False
            elif response[:2] == bytes([1,129]):
                if not self.in_pending:raise ValueError('unexpected IN completion')
                self.in_pending=False
                self.receive_usb(response[2:])
            else:raise ValueError('unexpected USB completion')
        outgoing = None
        if not self.out_busy and self.outgoing:
            protocol,payload=self.outgoing[0]
            packet=self.mux.pending or self.mux.prepare(protocol,payload)
            outgoing = struct.pack('<IBB',len(packet),1,1)+packet
        incoming = None if self.in_pending else struct.pack('<IBB',16384,129,1)
        batch = getattr(self.transport, 'send_batch', None)
        if outgoing is not None and incoming is not None and batch is not None:
            accepted = batch([outgoing, incoming])
            if type(accepted) is not int or accepted not in (0, 1, 2):
                raise ValueError('invalid accepted prefix length')
            out_sent, in_sent = accepted >= 1, accepted == 2
        else:
            out_sent = outgoing is not None and self.transport.send(outgoing)
            in_sent = incoming is not None and self.transport.send(incoming)
        if out_sent:
            self.mux.accepted();self.outgoing.popleft();self.out_busy=True
        if in_sent:
            self.in_pending=True

    def run(self):
        try:
            while not self.stop.is_set():
                self.tick()
                self.stop.wait(self.poll_interval)
        finally:
            self.stop.set()
            for state in self.connections.values():
                state['error']=state['error'] or 'pump stopped'
                state['ready'].set()
                state['socket'].close()
