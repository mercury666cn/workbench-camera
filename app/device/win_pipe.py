from __future__ import annotations

import ctypes
import msvcrt
import os
from ctypes import wintypes


PIPE_ACCESS_INBOUND = 0x00000001
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_PIPE_CONNECTED = 535

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
]
kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
kernel32.ConnectNamedPipe.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class NamedPipeServer:
    def __init__(self, name: str, buffer_size: int = 1024 * 1024) -> None:
        self.name = name
        self.path = rf"\\.\pipe\{name}"
        self.handle = kernel32.CreateNamedPipeW(
            self.path,
            PIPE_ACCESS_INBOUND,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            1,
            buffer_size,
            buffer_size,
            0,
            None,
        )
        if self.handle == INVALID_HANDLE_VALUE:
            raise OSError(f"无法创建命名管道：{ctypes.get_last_error()}")
        self._file = None

    def wait_client(self, timeout: float = 12) -> object:
        # ConnectNamedPipe blocks until scrcpy opens the pipe.
        ok = kernel32.ConnectNamedPipe(self.handle, None)
        if not ok and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
            raise OSError(f"等待 scrcpy 连接管道失败：{ctypes.get_last_error()}")
        fd = msvcrt.open_osfhandle(int(self.handle), os.O_RDONLY)
        self.handle = None  # fd now owns it
        self._file = os.fdopen(fd, "rb", buffering=0)
        return self._file

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None
