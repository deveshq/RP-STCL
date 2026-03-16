# -*- coding: utf-8 -*-

import sys
if sys.version_info < (3, 5):
    raise RuntimeError(
        "Python 3.5 or newer is required. Running: {}.{}.{}".format(
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