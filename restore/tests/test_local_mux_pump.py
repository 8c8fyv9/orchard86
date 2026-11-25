# SPDX-License-Identifier: GPL-3.0-or-later
import runpy,struct,threading,socket,unittest
from pathlib import Path
from collections import deque
Pump=runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-mux-pump.py')))['Pump']
class Transport:
 def __init__(self):self.sent=[];self.rx=deque()
 def send(self,p):self.sent.append(p);return True
 def receive(self):return self.rx.popleft() if self.rx else None
class Tests(unittest.TestCase):
 def test_batch_partial_acceptance_retries_only_in(self):
  t=Transport(); p=Pump(t,threading.Event()); attempted=[]
  def batch(frames):
   attempted.extend(frames)
   return 1
  t.send_batch=batch
  p.outgoing.append((6,b'payload'))
  p.tick()
  self.assertEqual([frame[4] for frame in attempted],[1,129])
  self.assertTrue(p.out_busy); self.assertFalse(p.in_pending); self.assertEqual(list(p.outgoing),[(6,b'payload')])
  p.tick()
  self.assertTrue(p.out_busy); self.assertTrue(p.in_pending)
  self.assertEqual(len(attempted),2)

 def test_independent_in_out(self):
  t=Transport();p=Pump(t,threading.Event());p.tick()
  self.assertTrue(p.in_pending);self.assertTrue(p.out_busy)
  self.assertEqual([x[4]for x in t.sent],[1,129])
  t.rx.append(bytes([1,1]));p.tick();self.assertFalse(p.out_busy);self.assertTrue(p.in_pending)
 def test_stream_and_fin(self):
  t=Transport();p=Pump(t,threading.Event());a,b=socket.socketpair();b.setblocking(False)
  s=dict(port=62078,socket=b,ready=threading.Event(),seq=0,ack=0,peer_ack=0,open=False,tx_fin=None,rx=None,rx_shutdown=False,error=None)
  p.connections[49152]=s
  def incoming(tx,sequence,ack,flags,payload=b''):
   body=struct.pack('!HHIIBBHHH',62078,49152,sequence,ack,80,flags,512,0,0)+payload
   p.receive(struct.pack('!IIIHH',6,len(body)+16,0xfaceface,tx,0)+body)
  try:
   incoming(0,0,1,18);self.assertTrue(s['ready'].is_set())
   incoming(1,1,1,16,b'original');s['rx'].drain(b.send);self.assertEqual(a.recv(100),b'original')
   incoming(2,1,1,16,b'original');self.assertEqual(s['ack'],9)
   incoming(3,9,1,17);self.assertTrue(s['rx'].eof_ready);self.assertEqual(s['ack'],10)
  finally:a.close();b.close()
 def test_actual_pump_ack_and_mux_wrap(self):
  p=Pump(Transport(),threading.Event());a,b=socket.socketpair()
  try:
   boundary=2**32
   s=dict(port=12346,socket=b,ready=threading.Event(),seq=boundary+16384,
          ack=1,peer_ack=boundary-16384,open=True,tx_fin=None,rx=None,
          rx_shutdown=False,error=None)
   p.connections[49152]=s;p.mux.peer_next=65535
   for mux_tx,wire_ack in ((65535,0),(0,16384),(1,16384)):
    tcp=struct.pack('!HHIIBBHHH',12346,49152,1,wire_ack,80,16,512,0,0)
    p.receive_usb(struct.pack('!IIIHH',6,36,0xfaceface,mux_tx,0)+tcp)
   self.assertEqual(s['peer_ack'],boundary+16384)
   self.assertEqual(p.mux.peer_next,2)
   p.tcp(49152,s,16,b'payload')
   self.assertEqual(struct.unpack_from('!I',p.outgoing[-1][1],4)[0],16384)
  finally:a.close();b.close()
 def test_usb_boundaries(self):
  p=Pump(Transport(),threading.Event());seen=[];p.receive=seen.append
  frame=struct.pack('!IIIHH',2,20016,0xfaceface,0,0)+bytes(20000)
  p.receive_usb(b'');p.receive_usb(frame[:7]);p.receive_usb(frame[7:16384])
  self.assertEqual(seen,[])
  p.receive_usb(frame[16384:]+frame+frame[:13]);self.assertEqual(seen,[frame,frame])
  p.receive_usb(frame[13:]);self.assertEqual(seen,[frame]*3)
  self.assertEqual(p.usb_input,b'')
 def test_guest_control_logged_without_session_teardown(self):
  p=Pump(Transport(),threading.Event());payload=bytes([3])+b'test transport failure'
  packet=struct.pack('!IIIHH',1,16+len(payload),0xfaceface,0,0)+payload
  p.receive_usb(packet)
  self.assertEqual(list(p.control_messages),[payload])
  self.assertFalse(p.stop.is_set())
  self.assertEqual(p.mux.peer_next,1)
 def test_usb_invalid_header(self):
  p=Pump(Transport(),threading.Event())
  for length in (0,65537):
   p.usb_input.clear()
   with self.assertRaises(ValueError):p.receive_usb(struct.pack('!IIIHH',2,length,0xfaceface,0,0))
 def test_peer_window_limits_and_resume(self):
  p=Pump(Transport(),threading.Event());a,b=socket.socketpair();b.setblocking(False)
  Buffer=runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-stream-buffer.py')))['ReceiveBuffer']
  s=dict(port=62078,socket=b,ready=threading.Event(),seq=1,ack=1,peer_ack=1,open=True,tx_fin=None,rx=Buffer(sequence=1),rx_shutdown=False,error=None,peer_window=256)
  p.connections[49152]=s
  try:
   a.sendall(bytes(1024));p.tick();self.assertEqual(s['seq'],257)
   p.tick();self.assertEqual(s['seq'],257)
   s['peer_ack']=257;s['peer_window']=0;p.tick();self.assertEqual(s['seq'],257)
   s['peer_window']=512;p.tick();self.assertEqual(s['seq'],769)
  finally:a.close();b.close()
 def test_poll_interval(self):
  self.assertEqual(Pump(Transport(),threading.Event()).poll_interval,.002)
  self.assertEqual(Pump(Transport(),threading.Event(),poll_interval=.0002).poll_interval,.0002)
  for value in (0,-1,float('nan'),float('inf'),2):
   with self.assertRaises(ValueError):Pump(Transport(),threading.Event(),poll_interval=value)
if __name__=='__main__':unittest.main()
