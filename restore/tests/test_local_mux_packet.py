# SPDX-License-Identifier: GPL-3.0-or-later
import pathlib,runpy,struct,unittest
parse=runpy.run_path(str((pathlib.Path(__file__).resolve().parents[1] / "transport" / 'local-mux-packet.py')))['parse']
def packet(flags=16,offset=80,payload=b''):
 body=struct.pack('!HHIIBBHHH',12345,49152,1,123,offset,flags,512,0,0)+payload
 return struct.pack('!IIIHH',6,16+len(body),0xfaceface,0,0)+body
class Tests(unittest.TestCase):
 def test_payload(self):self.assertEqual(parse(packet(payload=b'bytes'))['payload'],b'bytes')
 def test_private_extension_bits(self):
  p=parse(packet(offset=83,flags=18));self.assertEqual(p['flags'],18);self.assertEqual(p['payload'],b'')
 def test_rst_without_ack(self):
  p=parse(packet(flags=4));self.assertIsNone(p['acknowledgement']);self.assertEqual(p['flags'],4)
 def test_truncation(self):
  for n in range(36):
   with self.assertRaises(ValueError):parse(packet()[:n])
 def test_bad_header(self):
  for offset in (0,64,240):
   with self.assertRaises(ValueError):parse(packet(offset=offset))
 def test_syn_conflict(self):
  for flags in (3,6):
   with self.assertRaises(ValueError):parse(packet(flags=flags))
 def test_options_length(self):self.assertEqual(parse(packet(offset=96,payload=b'optsdata'))['payload'],b'data')
if __name__=='__main__':unittest.main()
