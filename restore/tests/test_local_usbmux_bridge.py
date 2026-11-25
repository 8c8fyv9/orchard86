# SPDX-License-Identifier: GPL-3.0-or-later
import runpy,socket,threading,time,unittest
from pathlib import Path
api=runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-usbmux-bridge.py')))
control=api['api']
class Test(unittest.TestCase):
 def test_opaque_connection(self):
  stop=threading.Event();guest,peer=socket.socketpair();ports=[]
  def connect(port):ports.append(port);return guest
  inventory=control['GuestInventory'](serial='test-only',product_id=1)
  bridge=api['Bridge'](inventory,connect,stop=stop,deadline=time.monotonic()+3)
  app,server=socket.socketpair();app.settimeout(2);peer.settimeout(2)
  thread=threading.Thread(target=bridge.handle,args=(server,));thread.start()
  try:
   control['send'](app,7,{'MessageType':'Connect','DeviceID':1,'PortNumber':socket.htons(62078)})
   self.assertEqual(control['receive'](app,request=False)[1]['Number'],0)
   app.sendall(b'original-plist-bytes');self.assertEqual(peer.recv(100),b'original-plist-bytes')
   peer.sendall(b'original-error');self.assertEqual(app.recv(100),b'original-error')
   app.shutdown(socket.SHUT_WR);peer.shutdown(socket.SHUT_WR);thread.join(2)
   self.assertEqual(ports,[62078]);self.assertEqual(bridge.errors,[])
  finally:stop.set();app.close();peer.close();thread.join(2)
 def test_no_success_before_connector(self):
  def fail(port):raise ConnectionError('guest SYN rejected')
  bridge=api['Bridge'](control['GuestInventory'](serial='test-only',product_id=1),fail,stop=threading.Event(),deadline=time.monotonic()+2)
  app,server=socket.socketpair();app.settimeout(2)
  thread=threading.Thread(target=bridge.handle,args=(server,));thread.start()
  control['send'](app,1,{'MessageType':'Connect','DeviceID':1,'PortNumber':socket.htons(62078)})
  self.assertEqual(app.recv(100),b'');thread.join();app.close();self.assertTrue(bridge.errors)
if __name__=='__main__':unittest.main()
