# -*- coding: utf-8 -*-

from RP_Lock import *

host, port = '192.168.0.104', 5000
Lock = RP_Server(host, port, 5065, RP_mode = 'monitor')
Lock.setup_server(loop=False)
Lock.start_server()host = os.environ.get("RP_LOCK_HOST", "192.168.0.101")
port = int(os.environ.get("RP_LOCK_PORT", "5000"))
loop_port = int(os.environ.get("RP_LOCK_LOOP_PORT", "5065"))
mode = os.environ.get("RP_LOCK_MODE", "scan")
