"""Bounded, read-only ALVR v20.14.1 event health client (stdlib only).

``open()`` checks the exact server version before opening the event WebSocket.
``wait(timeout)`` receives a bounded batch and returns ``fresh_stream``. Call it
again to continue receiving. Event timestamps are not trusted; proof expires
three seconds after local receipt. No event bodies or session data are exposed.

Transport failures and disconnects raise ``OSError`` (including ``TimeoutError``).
Invalid HTTP, version, WebSocket, or event data raises ``ProtocolError``. Its
messages contain only fixed descriptions, never response or event bodies. Both
failure paths close the connection and clear all stream proof. Call ``open()``
again after an unavailable endpoint; do not retry a version/protocol rejection
as though it were a healthy stream.
"""
import base64
from collections import deque
import hashlib
import json
import math
import os
import select
import socket
import struct
import time


_VERSION = b"20.14.1"
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_HEADER_LIMIT = 16384
_VERSION_LIMIT = 256
_FRAME_LIMIT = 1024 * 1024  # This size and larger are rejected.
_READ_SIZE = 65536
_MAX_FRAMES_PER_WAIT = 256
_MAX_IO_STEPS = 4096
_FRESH_SECONDS = 3.0
_REQUIRED = {
    "StatisticsSummary": ("video_packets_total", "video_packets_per_sec", "client_fps", "server_fps"),
    "GraphStatistics": ("decoder_s", "client_fps", "server_fps"),
}


class ProtocolError(Exception):
    """The ALVR peer violated the pinned version or read-only wire protocol."""


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout must be a finite nonnegative number")
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("timeout must be a finite nonnegative number")
    return float(value)


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


class Events:
    """Receive health statistics only from ``127.0.0.1:port``; never use a proxy.

    ``open(timeout=.5)`` has one total deadline for both HTTP connections.
    ``wait(timeout)`` has one total deadline and a 256-frame work limit. Either
    method may return before its deadline. A caller should continue calling
    ``wait`` while connected. ``close`` is idempotent and clears freshness.
    """

    def __init__(self, port=8082, clock=time.monotonic):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")
        self.port = port
        self._clock = clock
        self._socket = None
        self._buffer = bytearray()
        self._received = deque()
        self._proof = {}

    def _deadline(self, timeout):
        # A real monotonic deadline also bounds I/O with a paused injected clock.
        return self._clock() + timeout, time.monotonic() + timeout

    def _remaining(self, deadline):
        return max(0.0, min(deadline[0] - self._clock(), deadline[1] - time.monotonic()))

    def _ready(self, sock, deadline, writing=False):
        readable, writable, _ = select.select(
            [] if writing else [sock], [sock] if writing else [], [],
            self._remaining(deadline))
        return bool(writable if writing else readable)

    def _connect(self, deadline):
        remaining = self._remaining(deadline)
        if remaining <= 0:
            raise TimeoutError("ALVR connection deadline expired")
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=remaining)
        try:
            sock.setblocking(False)
        except OSError:
            sock.close()
            raise
        return sock

    def _send(self, sock, payload, deadline):
        offset = 0
        for _ in range(_MAX_IO_STEPS):
            if not self._ready(sock, deadline, writing=True):
                raise TimeoutError("ALVR write deadline expired")
            try:
                count = sock.send(payload[offset:])
            except (BlockingIOError, InterruptedError):
                if self._remaining(deadline) <= 0:
                    raise TimeoutError("ALVR write deadline expired") from None
                continue
            if count == 0:
                raise ConnectionError("ALVR connection closed")
            offset += count
            if offset == len(payload):
                return
            if self._remaining(deadline) <= 0:
                raise TimeoutError("ALVR write deadline expired")
        raise TimeoutError("ALVR write work limit reached")

    def _read(self, sock, deadline):
        for _ in range(_MAX_IO_STEPS):
            if self._remaining(deadline) <= 0:
                raise TimeoutError("ALVR read deadline expired")
            if not self._ready(sock, deadline):
                raise TimeoutError("ALVR read deadline expired")
            try:
                return sock.recv(_READ_SIZE)
            except (BlockingIOError, InterruptedError):
                if self._remaining(deadline) <= 0:
                    raise TimeoutError("ALVR read deadline expired") from None
        raise TimeoutError("ALVR read work limit reached")

    def _headers(self, sock, deadline):
        incoming = bytearray()
        for _ in range(_MAX_IO_STEPS):
            end = incoming.find(b"\r\n\r\n")
            if end >= 0:
                if end + 4 > _HEADER_LIMIT:
                    raise ProtocolError("ALVR HTTP headers exceed the size limit")
                break
            if len(incoming) >= _HEADER_LIMIT:
                raise ProtocolError("ALVR HTTP headers exceed the size limit")
            chunk = self._read(sock, deadline)
            if not chunk:
                raise ConnectionError("ALVR HTTP connection closed")
            incoming.extend(chunk)
        else:
            raise TimeoutError("ALVR HTTP work limit reached")

        lines = bytes(incoming[:end]).split(b"\r\n")
        status_parts = lines[0].split(b" ", 2)
        if (len(status_parts) < 2 or status_parts[0] not in (b"HTTP/1.0", b"HTTP/1.1") or
                len(status_parts[1]) != 3 or not status_parts[1].isdigit()):
            raise ProtocolError("Invalid ALVR HTTP status")
        headers = {}
        allowed = b"!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for line in lines[1:]:
            name, separator, value = line.partition(b":")
            if not separator or not name or any(byte not in allowed for byte in name):
                raise ProtocolError("Invalid ALVR HTTP header")
            name = name.lower()
            if name in headers or any(byte < 32 and byte != 9 or byte == 127 for byte in value):
                raise ProtocolError("Invalid ALVR HTTP header")
            headers[name] = value.strip(b" \t")
        if b"transfer-encoding" in headers:
            raise ProtocolError("Unsupported ALVR HTTP transfer encoding")
        return int(status_parts[1]), headers, bytes(incoming[end + 4:]), status_parts[0]

    def _check_version(self, sock, deadline):
        request = ("GET /api/version HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n"
                   "X-ALVR: true\r\nConnection: close\r\n\r\n").format(self.port).encode("ascii")
        self._send(sock, request, deadline)
        status, headers, body, _ = self._headers(sock, deadline)
        if status != 200:
            raise ProtocolError("ALVR version endpoint rejected the request")
        if len(body) > _VERSION_LIMIT:
            raise ProtocolError("ALVR version response exceeds the size limit")
        length = headers.get(b"content-length")
        if length is not None:
            if not length.isdigit() or len(length) > 3 or int(length) > _VERSION_LIMIT:
                raise ProtocolError("Invalid ALVR version response length")
            length = int(length)
        for _ in range(_MAX_IO_STEPS):
            if length is not None and len(body) >= length:
                if len(body) != length:
                    raise ProtocolError("Invalid ALVR version response length")
                break
            chunk = self._read(sock, deadline)
            if not chunk:
                if length is not None:
                    raise ConnectionError("ALVR version response was truncated")
                break
            body += chunk
            if len(body) > _VERSION_LIMIT:
                raise ProtocolError("ALVR version response exceeds the size limit")
        else:
            raise TimeoutError("ALVR version work limit reached")
        if body not in (_VERSION, b"v" + _VERSION):
            raise ProtocolError("ALVR version must be 20.14.1")

    def open(self, timeout=0.5):
        """Verify v20.14.1 and subscribe; return self, or raise a safe error."""
        timeout = _duration(timeout)
        self.close()
        deadline = self._deadline(timeout)
        version_socket = None
        event_socket = None
        try:
            version_socket = self._connect(deadline)
            self._check_version(version_socket, deadline)
            version_socket.close()
            version_socket = None
            event_socket = self._connect(deadline)
            key = base64.b64encode(os.urandom(16))
            request = ("GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n"
                       "X-ALVR: true\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ").format(self.port).encode("ascii")
            self._send(event_socket, request + key + b"\r\n\r\n", deadline)
            status, headers, remainder, http_version = self._headers(event_socket, deadline)
            expected = base64.b64encode(hashlib.sha1(key + _GUID).digest())
            connection_tokens = [part.strip().lower() for part in headers.get(b"connection", b"").split(b",")]
            if (status != 101 or http_version != b"HTTP/1.1" or
                    headers.get(b"upgrade", b"").lower() != b"websocket" or
                    b"upgrade" not in connection_tokens or
                    headers.get(b"sec-websocket-accept") != expected or
                    b"sec-websocket-extensions" in headers or b"sec-websocket-protocol" in headers or
                    b"content-length" in headers):
                raise ProtocolError("Invalid ALVR WebSocket handshake")
            self._socket = event_socket
            self._append(remainder)
            return self
        except (OSError, ProtocolError):
            if event_socket is not None and event_socket is not self._socket:
                event_socket.close()
            self.close()
            raise
        finally:
            if version_socket is not None:
                version_socket.close()

    def _append(self, data):
        if data:
            self._buffer.extend(data)
            self._received.append([len(data), self._clock()])

    def _consume(self, size):
        received_at = None
        remaining = size
        while remaining:
            chunk = self._received[0]
            taken = min(remaining, chunk[0])
            chunk[0] -= taken
            remaining -= taken
            received_at = chunk[1]
            if chunk[0] == 0:
                self._received.popleft()
        del self._buffer[:size]
        return received_at

    def _frame(self):
        data = self._buffer
        if len(data) < 2:
            return None
        first, second = data[0], data[1]
        opcode = first & 15
        if first & 0x70 or not first & 0x80 or second & 0x80 or opcode not in (1, 8, 9, 10):
            raise ProtocolError("Unsupported ALVR WebSocket frame")
        length = second & 0x7f
        offset = 2
        if length == 126:
            if len(data) < 4:
                return None
            length = struct.unpack("!H", data[2:4])[0]
            offset = 4
            if length < 126:
                raise ProtocolError("Noncanonical ALVR WebSocket frame length")
        elif length == 127:
            if len(data) < 10:
                return None
            length = struct.unpack("!Q", data[2:10])[0]
            offset = 10
            if length < 65536:
                raise ProtocolError("Noncanonical ALVR WebSocket frame length")
        if length >= _FRAME_LIMIT or opcode >= 8 and length > 125:
            raise ProtocolError("ALVR WebSocket frame exceeds the size limit")
        if len(data) < offset + length:
            return None
        payload = bytes(data[offset:offset + length])
        received_at = self._consume(offset + length)
        return opcode, payload, received_at

    def _event(self, payload, received_at):
        try:
            envelope = json.loads(payload.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            raise ProtocolError("Invalid ALVR event JSON") from None
        if not isinstance(envelope, dict):
            raise ProtocolError("Invalid ALVR event envelope")
        event = envelope.get("event_type")
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise ProtocolError("Invalid ALVR event envelope")
        # Unit enum variants have an id but no data. They do not prove health.
        kind, data = event["id"], event.get("data")
        if kind in _REQUIRED:
            if isinstance(data, dict) and all(_positive(data.get(field)) for field in _REQUIRED[kind]):
                self._proof[kind] = received_at
            else:
                self._proof.pop(kind, None)

    def _handle(self, decoded, deadline):
        opcode, payload, received_at = decoded
        if opcode == 1:
            self._event(payload, received_at)
        elif opcode == 9:
            mask = os.urandom(4)
            encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            self._send(self._socket, bytes([0x8a, 0x80 | len(payload)]) + mask + encoded, deadline)
        elif opcode == 8:
            if len(payload) == 1:
                raise ProtocolError("Invalid ALVR WebSocket close frame")
            if payload:
                code = struct.unpack("!H", payload[:2])[0]
                if code not in (1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014) and not 3000 <= code <= 4999:
                    raise ProtocolError("Invalid ALVR WebSocket close code")
                try:
                    payload[2:].decode("utf-8")
                except UnicodeError:
                    raise ProtocolError("Invalid ALVR WebSocket close text") from None
            raise ConnectionError("ALVR event connection closed")

    def wait(self, timeout):
        """Receive a bounded batch using select; return the current freshness."""
        timeout = _duration(timeout)
        if self._socket is None:
            raise ConnectionError("ALVR event connection is not open")
        deadline = self._deadline(timeout)
        frames = 0
        reads = 0
        try:
            while frames < _MAX_FRAMES_PER_WAIT and reads < _MAX_IO_STEPS:
                if timeout > 0 and self._remaining(deadline) <= 0:
                    break
                decoded = self._frame()
                if decoded is not None:
                    self._handle(decoded, deadline)
                    frames += 1
                    if timeout > 0 and self._remaining(deadline) <= 0:
                        break
                    continue
                if not self._ready(self._socket, deadline):
                    break
                try:
                    data = self._socket.recv(_READ_SIZE)
                except (BlockingIOError, InterruptedError):
                    if self._remaining(deadline) <= 0:
                        break
                    reads += 1
                    continue
                reads += 1
                if not data:
                    raise ConnectionError("ALVR event connection closed")
                self._append(data)
            return self.fresh_stream
        except (OSError, ProtocolError):
            self.close()
            raise

    @property
    def fresh_stream(self):
        """Both positive statistics types were received within three seconds."""
        now = self._clock()
        return self._socket is not None and all(
            kind in self._proof and 0 <= now - self._proof[kind] <= _FRESH_SECONDS
            for kind in _REQUIRED)

    def close(self):
        """Close without sending application requests and discard all proof."""
        sock, self._socket = self._socket, None
        self._proof.clear()
        self._buffer.clear()
        self._received.clear()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
