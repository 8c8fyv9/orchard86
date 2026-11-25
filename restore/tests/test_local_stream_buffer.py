# SPDX-License-Identifier: GPL-3.0-or-later
import pathlib,runpy,unittest
Buffer=runpy.run_path(str((pathlib.Path(__file__).resolve().parents[1] / "transport" / 'local-stream-buffer.py')))['ReceiveBuffer']
class Tests(unittest.TestCase):
 def test_eagain_after_accept_retains_ownership(self):
  b=Buffer();self.assertEqual(b.accept(1,b'fixture'),8)
  def blocked(data):raise BlockingIOError()
  self.assertEqual(b.drain(blocked),0);self.assertEqual(bytes(b.pending),b'fixture')
  self.assertEqual(b.accepted,b.delivered+len(b.pending)+b.aborted)
 def test_partial_write_exact_suffix(self):
  b=Buffer();b.accept(1,b'abcdef');out=[]
  def short(data):out.append(data[:2]);return min(2,len(data))
  while b.pending:b.drain(short)
  self.assertEqual(b''.join(out),b'abcdef');self.assertEqual(b.delivered,6)
 def test_capacity_rejects_before_ack(self):
  b=Buffer(limit=4);b.accept(1,b'abcd')
  with self.assertRaises(BufferError):b.accept(5,b'e')
  self.assertEqual(b.accepted_sequence,5);self.assertEqual(b.accepted,4)
 def test_abort_accounts_lost_not_delivered(self):
  b=Buffer();b.accept(1,b'abc');b.abort();self.assertEqual(b.aborted,3);self.assertEqual(b.delivered,0)
  with self.assertRaises(ValueError):b.accept(4,b'x')
 def test_zero_write_is_not_success(self):
  b=Buffer();b.accept(1,b'x')
  with self.assertRaises(ConnectionError):b.drain(lambda data:0)
  self.assertEqual(bytes(b.pending),b'x')
 def test_real_socketpair_slow_reader(self):
  import socket
  left,right=socket.socketpair()
  try:
   left.setblocking(False);right.setblocking(False);left.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4096)
   b=Buffer();payload=bytes(range(256))*1024;b.accept(1,payload)
   self.assertGreater(b.drain(left.send),0)
   for _ in range(100):
    if b.drain(left.send)==0:break
   else:self.fail('backpressure not reached')
   self.assertTrue(b.pending);received=bytearray()
   for _ in range(10000):
    try:received.extend(right.recv(65536))
    except BlockingIOError:pass
    b.drain(left.send)
    self.assertEqual(b.accepted,b.delivered+len(b.pending))
    if len(received)==len(payload):break
   self.assertEqual(bytes(received),payload);self.assertFalse(b.pending)
  finally:left.close();right.close()
 def test_fin_waits_for_pending_bytes(self):
  b=Buffer();b.accept(1,b'abc');self.assertEqual(b.accept_fin(4),5)
  self.assertFalse(b.eof_ready);b.drain(lambda data:len(data));self.assertTrue(b.eof_ready)
  self.assertEqual(b.accepted,3);self.assertEqual(b.delivered,3)
  self.assertEqual(b.accept_fin(4),5)
  with self.assertRaises(ValueError):b.accept(5,b'x')
 def test_socket_half_close_preserves_response(self):
  import socket
  left,right=socket.socketpair()
  try:
   left.settimeout(1);right.settimeout(1)
   b=Buffer();b.accept(1,b'request');b.accept_fin(8)
   b.drain(left.send);self.assertTrue(b.eof_ready)
   left.shutdown(socket.SHUT_WR)
   self.assertEqual(right.recv(64),b'request');self.assertEqual(right.recv(64),b'')
   right.sendall(b'response');self.assertEqual(left.recv(64),b'response')
  finally:left.close();right.close()
 def test_fin_only_and_duplicate(self):
  b=Buffer();self.assertEqual(b.accept_fin(1),2);self.assertTrue(b.eof_ready)
  self.assertEqual(b.accept_fin(1),2)
  with self.assertRaises(ValueError):b.accept_fin(2)
 def test_wrong_fin_and_abort(self):
  b=Buffer()
  with self.assertRaises(ValueError):b.accept_fin(2)
  self.assertIsNone(b.fin_sequence);b.accept_fin(1);b.abort();self.assertFalse(b.eof_ready)
 def test_disorder_rejected(self):
  b=Buffer()
  with self.assertRaises(ValueError):b.accept(2,b'x')
if __name__=='__main__':unittest.main()
