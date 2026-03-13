# -*- coding: utf-8 -*-
"""
Created on Fri May 13 10:23:32 2022

@author: epultinevicius


In this module, a sender class is defined which handles all of the
communication with the RedPitaya based on socket servers.
This will be the base for the LockClient class which will be used to handle
the STCL remotely using individual RedPitayas.

"""
# modules used for socket communication
import socket
import errno
import selectors
import traceback
import libclient
import threading

# module for ssh communication
import paramiko

# used for waiting whenever code is remotely excecuted on a RedPitaya,
# since that can take some time.
from time import sleep

# for path finding in both windows and unix operating systems
from pathlib import (
    PurePosixPath,
    Path,
)  # just PosixPath did not work on our Windows machine...
import os
import sys

# dictionary of files required for the lock to run on the redpitaya and the
# directory they are stored in.
directory = Path("RP_side")
filenames = dict(
    Run="RunLock.py",
    Lock="RP_Lock.py",
    Lib="libserver.py",
    Peaks="peak_finders.py",
    Compat="rp_compat.py",
)

# find the required filepaths! They are expected to be found in the pythonpath:
paths = sys.path
# initialize empty dictionary for the filepaths
filepaths = dict()
# Find the files in the filepaths. The directory should have a unique name to avoid confusion with other libraries.
for p in paths:
    for key, val in filenames.items():  # search for each filename
        filepath = Path(p, Path(directory, val))
        if filepath.exists():  # if found, then add it to the dictionary
            the_path = p
            filepaths[key] = filepath

DIR = Path(the_path, "settings")  # save the found pythonpath


_CONNECT_INPROGRESS = {
    0,
    errno.EINPROGRESS,
    errno.EWOULDBLOCK,
    errno.EALREADY,
    getattr(errno, "WSAEWOULDBLOCK", 10035),
    getattr(errno, "WSAEALREADY", 10037),
    getattr(errno, "WSAEINPROGRESS", 10036),
}


class Sender:
    """
    This class is the framework used to establish the communication
    between the PC and Redpitaya. Most of this is based of the RealPython socket
    programming guide (https://realpython.com/python-sockets/ , 23.02.2023).
    """

    def __init__(self, DIR=DIR):
        """

        Parameters
        ----------
        DIR : Path
            This path will be used by default for storing the lock settings
            json-files. Can be changed as desired. The default is the directory
            where all the modules are loaded from.

        """
        self.sel = selectors.DefaultSelector()
        self.mode = "scan"  # by default, assume the redpitaya scans the cavity.
        self.state = 0
        self.running = False
        self.DIR = DIR

    def event_loop(self):
        """
        This is the event_loop which handles the communication. Whenever multiple
        traces are to be acquired from the redpitaya, (acquire_ch_n), the buffersize is
        increased to reduce the time to send data. The eventloop is properly
        described in the RealPython socket example. Here, the state variable is added
        in order to properly deal with loop_action().

        Returns
        -------
        whatever the remotely executed function on the redpitaya returns.

        """
        self.running = True  # set the running variable to True
        # self.sel = selectors.DefaultSelector()
        try:
            while True:
                if not self.sel.get_map():
                    sleep(0)
                else:
                    events = self.sel.select(timeout=1)
                    for key, mask in events:
                        message = key.data
                        if key.data is not None:
                            try:
                                if self.mode == "monitor":
                                    message.buffersize = int(2**18)
                                else:
                                    message.buffersize = int(2**12)
                                message.process_events(mask)
                            except Exception:
                                print(
                                    f"Main: Error: Exception for {message.addr}:\n"
                                    f"{traceback.format_exc()}"
                                )
                                message.close()
                    if not self.running:
                        break

        except KeyboardInterrupt:
            print("Caught keyboard interrupt, exiting")
            message.close()
        finally:
            return

    def start_event_loop(self):
        if not self.running:
            self.el_thread = threading.Thread(target=self.event_loop)
            self.el_thread.daemon = True
            self.el_thread.start()
        else:
            print("Event loop already running!")

    def stop_event_loop(self):
        self.running = False


class RP_connection:
    def __init__(self, addr, mode="scan"):
        self.addr = addr
        self.mode = mode
        self.lsock = None
        self.loop_running = False
        self.connected = False

    def _check_ext_scan(func):
        def inner(self, *args, **kwargs):
            if self.mode == "ext_scan":
                return None
            else:
                return func(self, *args, **kwargs)

        return inner

    @_check_ext_scan
    def reboot(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        ssh.connect(self.addr[0], port=22, username="root", password="root", timeout=5)
        ssh.exec_command("reboot")
        ssh.close()
        print("Rebooting, please wait a bit before attempting to reconnect.")
        return

    @_check_ext_scan
    def upload_current(self):
        paths = sys.path
        filepaths = dict()
        for p in paths:
            for key, val in filenames.items():
                filepath = Path(p, Path(directory, val))
                if filepath.exists():
                    filepaths[key] = filepath
        hostname = self.addr[0]
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        ssh.connect(hostname, port=22, username="root", password="root", timeout=5)
        sftp = ssh.open_sftp()
        for key in ["Lock", "Lib", "Run", "Peaks", "Compat"]:
            path = PurePosixPath("/home/jupyter/RedPitaya", filenames[key])
            localpath = filepaths[key]
            if key == "Run":
                with localpath.open("r", encoding="utf-8") as f:
                    lines = f.readlines()

                def _replace_or_append(lines, prefix, replacement):
                    for i, line in enumerate(lines):
                        if line.strip().startswith(prefix):
                            lines[i] = replacement
                            return lines
                    lines.append(replacement)
                    return lines

                lines = _replace_or_append(
                    lines,
                    "host =",
                    f'host = os.environ.get("RP_LOCK_HOST", "{hostname}")\n',
                )
                lines = _replace_or_append(
                    lines,
                    "port =",
                    'port = int(os.environ.get("RP_LOCK_PORT", "5000"))\n',
                )
                lines = _replace_or_append(
                    lines,
                    "loop_port =",
                    'loop_port = int(os.environ.get("RP_LOCK_LOOP_PORT", "5065"))\n',
                )
                lines = _replace_or_append(
                    lines,
                    "mode =",
                    f'mode = os.environ.get("RP_LOCK_MODE", "{self.mode}")\n',
                )

                with localpath.open("w", encoding="utf-8") as f:
                    f.writelines(lines)
            sftp.put(str(localpath), str(path))

            print(f"Uploaded {key} to {hostname}:{path}")
        sftp.close()
        ssh.close()

    @_check_ext_scan
    def start_host_server(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy)
        ssh.connect(self.addr[0], port=22, username="root", password="root", timeout=5)
        ssh.exec_command("python3 /home/jupyter/RedPitaya/RunLock.py")
        ssh.close()
        self.connected = True
        return "connected"

    @_check_ext_scan
    def connect_socket(self, addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            err = sock.connect_ex(addr)
            if err not in _CONNECT_INPROGRESS:
                sock.close()
                raise OSError(err, os.strerror(err))
        except OSError as exc:
            print(f"Socket connect failed for {addr}: {exc}")
            return None
        sock.setblocking(False)
        return sock

    @_check_ext_scan
    def send(self, Sender, action, value="Hello World!", loop_action=False, loop=False):
        if Sender.running:
            request = self.create_request(action, value)
            if not loop:
                sock = self.connect_socket(self.addr)
                addr = self.addr
                stop = True
            else:
                sock = self.lsock
                addr = (self.addr[0], 5065)
                stop = action == "stop"

            if sock is None:
                return f"Socket connection failed: {addr}"

            event_state = selectors.EVENT_READ | selectors.EVENT_WRITE
            message = libclient.Message(Sender.sel, sock, addr, request, stop=stop)
            Sender.sel.register(sock, event_state, data=message)

            if loop_action:
                self.loop_running = True

            while True:
                sleep(0)
                if loop_action and self.loop_running and self.lsock is None:
                    try:
                        key = Sender.sel.get_key(sock)
                    except KeyError:
                        key = None
                    if key is not None and (key.events & selectors.EVENT_READ):
                        laddr = (self.addr[0], 5065)
                        sleep(2)
                        self.lsock = self.connect_socket(laddr)
                        sleep(0.5)
                        if self.lsock is None:
                            self.loop_running = False
                            return f"Loop socket connection failed: {laddr}"
                        try:
                            self.lsock.getpeername()
                        except Exception as exp:
                            print(f"Exception occured during connection: {exp}")
                            self.loop_running = False
                            return f"Exception occured during connection: {exp}"
                        print(f"connected to {self.lsock}")

                if message.selkey is not None:
                    if self.loop_running and action == "stop":
                        self.loop_running = False
                    break

            if message.response is None:
                if message.error is not None:
                    result = f"Socket error: {message.error}"
                else:
                    result = "No response (socket closed)"
            else:
                result = message.response.get("result")
            if loop_action:
                self.lsock = None
        else:
            print("Event_loop not running!")
            result = None

        return result

    @_check_ext_scan
    def create_request(self, action, value):
        return dict(
            type="text/json",
            encoding="utf-8",
            content=dict(action=action, value=value),
        )
