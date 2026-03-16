# -*- coding: utf-8 -*-

import sys
if sys.version_info < (3, 5):
host, port = '192.168.0.200', 5000
Lock = RP_Server(host, port, 5065, RP_mode = 'scan')
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
    )

from RP_Lock import *

host, port = '192.168.0.104', 5000
Lock = RP_Server(host, port, 5065, RP_mode = 'monitor')
Lock.setup_server(loop=False)
Lock.start_server()