# SPDX-License-Identifier: GPL-3.0-or-later
import runpy,socket,struct,unittest
from pathlib import Path
Endpoint=runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-usb-packet-endpoint.py')))['Endpoint']
class Tests(unittest.TestCase):
 def test_duplex(self):
  a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
  try:
   e=Endpoint(a)
   self.assertEqual(e.handle({'operation':'receive'}),{'available':False})
   for frame in (struct.pack('<IBB',16384,129,1),struct.pack('<IBB',3,1,1)+b'out'):
    self.assertTrue(e.handle({'operation':'send','frame_hex':frame.hex()})['accepted'])
    self.assertEqual(b.recv(100),frame)
   b.send(bytes([1,1]));b.send(bytes([1,129])+b'in')
   self.assertEqual(e.handle({'operation':'receive'})['reply_hex'],'0101')
   self.assertEqual(e.handle({'operation':'receive'})['reply_hex'],'0181696e')
  finally:a.close();b.close()
 def test_bad_length(self):
  a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
  try:
   e=Endpoint(a)
   with self.assertRaises(ValueError):e.handle({'operation':'send','frame_hex':struct.pack('<IBB',4,1,1).hex()})
   self.assertEqual(e.handle({'operation':'receive'}),{'available':False})
  finally:a.close();b.close()
if __name__=='__main__':unittest.main()
