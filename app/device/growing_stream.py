from __future__ import annotations

import io
import threading


class GrowingStream(io.RawIOBase):
    """Pipe-backed buffer that allows limited seeking so PyAV can probe MKV."""

    def __init__(self, source) -> None:
        super().__init__()
        self._source = source
        self._buf = bytearray()
        self._pos = 0
        self._eof = False
        self._error: BaseException | None = None
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._pump, name="pipe-pump", daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            while True:
                chunk = self._source.read(64 * 1024)
                with self._cv:
                    if not chunk:
                        self._eof = True
                        self._cv.notify_all()
                        return
                    self._buf.extend(chunk)
                    self._cv.notify_all()
        except BaseException as exc:
            with self._cv:
                self._error = exc
                self._eof = True
                self._cv.notify_all()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        with self._cv:
            if size < 0:
                while not self._eof:
                    self._cv.wait(timeout=0.2)
                    if self._error:
                        raise self._error
                data = bytes(self._buf[self._pos :])
                self._pos = len(self._buf)
                return data
            while self._pos + size > len(self._buf) and not self._eof:
                self._cv.wait(timeout=0.2)
                if self._error:
                    raise self._error
            end = min(self._pos + size, len(self._buf))
            data = bytes(self._buf[self._pos : end])
            self._pos = end
            return data

    def seek(self, offset: int, whence: int = 0) -> int:
        with self._cv:
            if whence == io.SEEK_SET:
                target = offset
            elif whence == io.SEEK_CUR:
                target = self._pos + offset
            elif whence == io.SEEK_END:
                # Live stream has no real EOF; report current buffered size.
                target = len(self._buf) + offset
            else:
                raise OSError(22, "invalid whence")
            if target < 0:
                target = 0
            self._pos = target
            return self._pos

    def wait_bytes(self, minimum: int, timeout: float = 8.0) -> None:
        deadline = timeout
        with self._cv:
            while len(self._buf) < minimum and not self._eof and deadline > 0:
                self._cv.wait(timeout=0.2)
                deadline -= 0.2
                if self._error:
                    raise self._error
            if len(self._buf) < minimum and not self._eof:
                raise TimeoutError("相机流还没有写出数据")

    def tell(self) -> int:
        with self._cv:
            return self._pos

    def close(self) -> None:
        super().close()
        try:
            self._source.close()
        except Exception:
            pass
