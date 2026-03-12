# -*- coding: utf-8 -*-

import os

host, port = '192.168.0.101', 5000
Lock = RP_Server(host, port, 5065, RP_mode = 'scan')

host = os.environ.get("RP_LOCK_HOST", "0.0.0.0")
port = int(os.environ.get("RP_LOCK_PORT", "5000"))
loop_port = int(os.environ.get("RP_LOCK_LOOP_PORT", "5065"))
mode = os.environ.get("RP_LOCK_MODE", "monitor")

Lock = RP_Server(host, port, loop_port, RP_mode=mode)
Lock.setup_server(loop=False)
Lock.start_server()
