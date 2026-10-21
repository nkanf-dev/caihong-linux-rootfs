"""Host-only ALVR protocol tests. All socket I/O is mocked."""
import base64
from collections import deque
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import alvr_events as ae


KEY = base64.b64encode(b"K" * 16).decode("ascii")
ACCEPT = base64.b64encode(hashlib.sha1(
    (KEY + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
).digest()).decode("ascii")
SUMMARY = {"video_packets_total": 10, "video_packets_per_sec": 5,
           "client_fps": 90, "server_fps": 90}
GRAPH = {"decoder_s": 0.005, "client_fps": 90, "server_fps": 90}


def http(body=b"20.14.1", status=b"200 OK", headers=b""):
    return (b"HTTP/1.1 " + status + b"\r\nContent-Length: " +
            str(len(body)).encode("ascii") + b"\r\n" + headers + b"\r\n" + body)


def upgrade(accept=ACCEPT, extra=b""):
    return (b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: keep-alive, Upgrade\r\nSec-WebSocket-Accept: " +
            accept.encode("ascii") + b"\r\n" + extra + b"\r\n")


def frame(payload, opcode=1, fin=True, mask=False, rsv=False):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    size = len(payload)
    start = bytes([(0x80 if fin else 0) | (0x40 if rsv else 0) | opcode])
    flag = 0x80 if mask else 0
    if size < 126:
        start += bytes([flag | size])
    elif size < 65536:
        start += bytes([flag | 126]) + struct.pack("!H", size)
    else:
        start += bytes([flag | 127]) + struct.pack("!Q", size)
    return start + (b"MASK" if mask else b"") + payload


def event(kind, data, timestamp="old-or-untrusted-timestamp"):
    return frame(json.dumps({"timestamp": timestamp,
                             "event_type": {"id": kind, "data": data}}))


def stream_frames():
    return event("StatisticsSummary", SUMMARY) + event("GraphStatistics", GRAPH)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeSocket:
    def __init__(self, *chunks):
        self.chunks = deque(chunks)
        self.sent = bytearray()
        self.closed = False
        self.blocking = None
        self.recv_calls = 0
        self.send_limit = None

    def setblocking(self, value):
        self.blocking = value

    def recv(self, size):
        self.recv_calls += 1
        if not self.chunks:
            raise BlockingIOError()
        chunk = self.chunks.popleft()
        if isinstance(chunk, Exception):
            raise chunk
        result = chunk[:size]
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
        return result

    def send(self, data):
        count = len(data) if self.send_limit is None else min(len(data), self.send_limit)
        self.sent.extend(data[:count])
        return count

    def close(self):
        self.closed = True


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = Clock()
        self.select_timeouts = []
        self.stack.enter_context(patch.object(ae.os, "urandom", side_effect=lambda n: b"K" * n))
        self.stack.enter_context(patch.object(ae.select, "select", side_effect=self.select))

    def select(self, readers, writers, errors, timeout):
        self.assertGreaterEqual(timeout, 0)
        self.select_timeouts.append(timeout)
        return ([sock for sock in readers if sock.chunks], list(writers), [])

    def connect(self, version=None, handshake=None, timeout=0.5):
        self.version_socket = FakeSocket(http() if version is None else version)
        self.websocket = FakeSocket(upgrade() if handshake is None else handshake)
        self.connections = self.stack.enter_context(patch.object(
            ae.socket, "create_connection", side_effect=[self.version_socket, self.websocket]))
        self.events = ae.Events(port=8082, clock=self.clock)
        self.addCleanup(self.events.close)
        self.events.open(timeout=timeout)
        return self.events

    def deliver(self, *chunks, timeout=0):
        self.websocket.chunks.extend(chunks)
        return self.events.wait(timeout)

    def assert_protocol_rejected(self, data):
        self.connect()
        with self.assertRaises(ae.ProtocolError):
            self.deliver(data)
        self.assertFalse(self.events.fresh_stream)
        self.assertTrue(self.websocket.closed)

    def test_open_uses_exact_loopback_readonly_paths_and_no_proxy(self):
        with patch.dict(os.environ, {"http_proxy": "http://invalid:1", "ALL_PROXY": "bad"}):
            events = self.connect()
        self.assertIs(events.open.__self__, events)
        self.assertEqual(self.connections.call_count, 2)
        for call in self.connections.call_args_list:
            self.assertEqual(call.args, (("127.0.0.1", 8082),))
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 0.5)
        self.assertTrue(self.version_socket.closed)
        self.assertFalse(self.websocket.closed)
        self.assertIs(self.websocket.blocking, False)
        self.assertIn(b"GET /api/version HTTP/1.1\r\n", self.version_socket.sent)
        self.assertIn(b"GET /api/events HTTP/1.1\r\n", self.websocket.sent)
        self.assertIn(b"Host: 127.0.0.1:8082\r\n", self.websocket.sent)
        self.assertIn(b"X-ALVR: true\r\n", self.websocket.sent)
        self.assertIn(b"Sec-WebSocket-Key: " + KEY.encode() + b"\r\n", self.websocket.sent)
        self.assertNotIn(b"GetSession", self.websocket.sent)
        self.assertFalse(events.fresh_stream)

    def test_version_accepts_optional_leading_v(self):
        self.connect(version=http(b"v20.14.1"))

    def test_version_can_be_close_delimited(self):
        self.version_socket = FakeSocket(b"HTTP/1.1 200 OK\r\n\r\n20.14.1", b"")
        self.websocket = FakeSocket(upgrade())
        self.stack.enter_context(patch.object(ae.socket, "create_connection",
                                             side_effect=[self.version_socket, self.websocket]))
        events = ae.Events(clock=self.clock)
        self.addCleanup(events.close)
        events.open()
        self.assertFalse(events.fresh_stream)

    def test_unavailable_endpoint_is_oserror(self):
        with patch.object(ae.socket, "create_connection", side_effect=ConnectionRefusedError()):
            with self.assertRaises(OSError):
                ae.Events(clock=self.clock).open()

    def test_wrong_version_and_arbitrary_body_raise_safe_protocol_error(self):
        for body in (b"20.14.0", b"20.14.10", b"vv20.14.1", b"secret-session-body", b"\xff"):
            with self.subTest(body=body), self.assertRaises(ae.ProtocolError) as error:
                self.connect(version=http(body))
            self.assertNotIn("secret-session-body", str(error.exception))
            self.assertEqual(self.connections.call_count, 1)
            self.assertTrue(self.version_socket.closed)

    def test_version_error_status_is_protocol_error_without_response_body(self):
        with self.assertRaises(ae.ProtocolError) as error:
            self.connect(version=http(b"private-session", status=b"500 private-session"))
        self.assertNotIn("private-session", str(error.exception))

    def test_bad_http_and_handshakes_fail_closed(self):
        versions = [b"not HTTP\r\n\r\n", http(headers=b"Content-Length: 7\r\n"),
                    http(headers=b"Transfer-Encoding: chunked\r\n"),
                    b"HTTP/1.1 200 OK\r\nX: " + b"a" * 20000 + b"\r\n\r\n",
                    http(b"a" * 1024)]
        for version in versions:
            with self.subTest(version=version[:50]), self.assertRaises(ae.ProtocolError):
                self.connect(version=version)
        handshakes = [upgrade(accept="wrong"), http(),
                      upgrade().replace(b"Upgrade: websocket", b"Upgrade: other"),
                      upgrade().replace(b"keep-alive, Upgrade", b"close"),
                      upgrade(extra=b"Sec-WebSocket-Extensions: permessage-deflate\r\n"),
                      upgrade(extra=b"Sec-WebSocket-Protocol: unexpected\r\n")]
        for handshake in handshakes:
            with self.subTest(handshake=handshake), self.assertRaises(ae.ProtocolError):
                self.connect(handshake=handshake)
            self.assertTrue(self.websocket.closed)

    def test_http_1_0_upgrade_is_not_rfc6455(self):
        with self.assertRaises(ae.ProtocolError):
            self.connect(handshake=upgrade().replace(b"HTTP/1.1", b"HTTP/1.0"))

    def test_open_deadline_is_shared_across_connections(self):
        original_select = self.select
        def advancing_select(readers, writers, errors, timeout):
            result = original_select(readers, writers, errors, timeout)
            self.clock.now += 0.1
            return result
        with patch.object(ae.select, "select", side_effect=advancing_select):
            self.connect(timeout=0.5)
        self.assertLess(self.connections.call_args_list[1].kwargs["timeout"], 0.31)

    def test_dribbling_http_read_stops_at_deadline(self):
        original_select = self.select
        def advancing_select(readers, writers, errors, timeout):
            result = original_select(readers, writers, errors, timeout)
            self.clock.now += 0.1
            return result
        self.version_socket = FakeSocket(*(bytes([value]) for value in http()))
        connection = self.stack.enter_context(patch.object(
            ae.socket, "create_connection", return_value=self.version_socket))
        with patch.object(ae.select, "select", side_effect=advancing_select):
            with self.assertRaises(OSError):
                ae.Events(clock=self.clock).open(timeout=0.5)
        self.assertLessEqual(self.version_socket.recv_calls, 5)
        self.assertEqual(connection.call_count, 1)
        self.assertTrue(self.version_socket.closed)

    def test_wait_stops_reading_partial_frame_when_deadline_expires(self):
        self.connect()
        original_select = self.select
        def advancing_select(readers, writers, errors, timeout):
            result = original_select(readers, writers, errors, timeout)
            self.clock.now += 0.2
            return result
        data = stream_frames()
        with patch.object(ae.select, "select", side_effect=advancing_select):
            self.deliver(data[:7], data[7:], timeout=0.1)
        self.assertTrue(self.websocket.chunks)
        self.assertFalse(self.events.fresh_stream)
        self.assertTrue(self.events.wait(0))

    def test_one_byte_handshake_reads_and_transient_would_block(self):
        self.version_socket = FakeSocket(BlockingIOError(), *(bytes([value]) for value in http()))
        self.websocket = FakeSocket(*(bytes([value]) for value in upgrade()))
        self.stack.enter_context(patch.object(ae.socket, "create_connection",
                                             side_effect=[self.version_socket, self.websocket]))
        events = ae.Events(clock=self.clock)
        self.addCleanup(events.close)
        events.open()
        self.websocket.chunks.extend([BlockingIOError(), stream_frames()])
        self.assertTrue(events.wait(0.1))

    def test_wait_socket_error_clears_proof(self):
        self.connect()
        self.deliver(stream_frames())
        with self.assertRaises(OSError):
            self.deliver(ConnectionResetError())
        self.assertFalse(self.events.fresh_stream)
        self.assertTrue(self.websocket.closed)

    def test_incomplete_handshake_times_out_within_budget(self):
        with self.assertRaises(OSError):
            self.connect(handshake=b"HTTP/1.1 101")
        self.assertTrue(self.websocket.closed)
        self.assertTrue(self.select_timeouts)
        self.assertLessEqual(max(self.select_timeouts), 0.5)

    def test_partial_handshake_and_event_remainder_are_preserved(self):
        self.connect(handshake=upgrade() + stream_frames())
        self.events.wait(0)
        self.assertTrue(self.events.fresh_stream)

    def test_both_new_statistics_types_are_required(self):
        self.connect()
        self.deliver(event("StatisticsSummary", SUMMARY))
        self.assertFalse(self.events.fresh_stream)
        self.assertTrue(self.deliver(event("GraphStatistics", GRAPH)))
        self.assertTrue(self.events.fresh_stream)

    def test_each_proof_expires_after_three_seconds(self):
        self.connect()
        self.deliver(event("GraphStatistics", GRAPH))
        self.clock.now += 2
        self.deliver(event("StatisticsSummary", SUMMARY))
        self.clock.now += 1
        self.assertTrue(self.events.fresh_stream)
        self.clock.now += 0.001
        self.assertFalse(self.events.fresh_stream)
        self.deliver(event("GraphStatistics", GRAPH))
        self.assertTrue(self.events.fresh_stream)
        self.clock.now += 2.001
        self.assertFalse(self.events.fresh_stream)

    def test_buffered_events_keep_their_original_receive_time(self):
        self.connect(handshake=upgrade() + stream_frames())
        self.clock.now += 3.001
        self.events.wait(0)
        self.assertFalse(self.events.fresh_stream)
        self.deliver(stream_frames())
        self.assertTrue(self.events.fresh_stream)

    def test_event_timestamp_cannot_make_expired_proof_fresh(self):
        self.connect()
        self.deliver(event("StatisticsSummary", SUMMARY, timestamp="2999-01-01"),
                     event("GraphStatistics", GRAPH, timestamp="2999-01-01"))
        self.clock.now += 3.001
        self.assertFalse(self.events.fresh_stream)

    def test_every_required_measure_must_be_finite_positive_number(self):
        self.connect()
        for kind, valid in (("StatisticsSummary", SUMMARY), ("GraphStatistics", GRAPH)):
            for field in valid:
                for bad in (0, -1, None, "1", True, float("nan"), float("inf"), 10 ** 400):
                    with self.subTest(kind=kind, field=field, bad=bad):
                        self.deliver(stream_frames())
                        self.assertTrue(self.events.fresh_stream)
                        data = dict(valid, **{field: bad})
                        self.deliver(event(kind, data))
                        self.assertFalse(self.events.fresh_stream)
                data = dict(valid)
                del data[field]
                self.deliver(stream_frames(), event(kind, data))
                self.assertFalse(self.events.fresh_stream)

    def test_zero_or_bad_latest_sample_revokes_previous_proof(self):
        self.connect()
        self.deliver(stream_frames())
        self.deliver(event("GraphStatistics", {}))
        self.assertFalse(self.events.fresh_stream)
        self.deliver(event("GraphStatistics", GRAPH))
        self.assertTrue(self.events.fresh_stream)
        self.deliver(event("StatisticsSummary", []))
        self.assertFalse(self.events.fresh_stream)

    def test_unknown_event_cannot_prove_stream(self):
        self.connect()
        self.deliver(event("Session", {"private": "not-output"}), event("Tracking", GRAPH),
                     frame('{"event_type":{"id":"ServerRequestsSelfRestart"}}'))
        self.assertFalse(self.events.fresh_stream)

    def test_missing_statistics_data_revokes_previous_proof(self):
        self.connect()
        self.deliver(stream_frames())
        self.deliver(frame('{"event_type":{"id":"GraphStatistics"}}'))
        self.assertFalse(self.events.fresh_stream)

    def test_wait_keeps_partial_frames_and_is_select_bounded(self):
        self.connect()
        data = stream_frames()
        self.assertFalse(self.deliver(data[:7], timeout=0.2))
        self.assertTrue(self.deliver(data[7:], timeout=0.2))
        self.assertLessEqual(max(self.select_timeouts[-2:]), 0.2)

    def test_wait_idle_does_not_sleep_or_drop_fresh_proof(self):
        self.connect()
        self.deliver(stream_frames())
        before = self.websocket.recv_calls
        self.assertTrue(self.events.wait(0.1))
        self.assertEqual(self.websocket.recv_calls, before)
        self.assertLessEqual(self.select_timeouts[-1], 0.1)

    def test_ping_sends_masked_pong_without_exposing_payload(self):
        self.connect()
        self.websocket.sent.clear()
        self.deliver(frame(b"ping-data", opcode=9), stream_frames())
        data = bytes(self.websocket.sent)
        self.assertEqual(data[:2], b"\x8a\x89")
        mask, payload = data[2:6], data[6:]
        self.assertEqual(bytes(value ^ mask[index % 4] for index, value in enumerate(payload)),
                         b"ping-data")
        self.assertTrue(self.events.fresh_stream)

    def test_pong_does_not_prove_stream(self):
        self.connect()
        self.deliver(frame(b"pong", opcode=10))
        self.assertFalse(self.events.fresh_stream)

    def test_extended_frame_lengths_and_partial_sends(self):
        self.connect()
        self.websocket.send_limit = 2
        self.deliver(frame(b"ping", opcode=9),
                     event("Log", {"text": "a" * 300}),
                     event("Log", {"text": "a" * 70000}), stream_frames(), timeout=0.2)
        self.assertTrue(self.events.fresh_stream)

    def test_masked_fragmented_binary_reserved_or_rsv_frames_rejected(self):
        for data in (frame(b"x", mask=True), frame(b"x", fin=False),
                     frame(b"x", opcode=0), frame(b"x", opcode=2),
                     frame(b"x", opcode=3), frame(b"x", rsv=True)):
            with self.subTest(data=data):
                self.assert_protocol_rejected(data)

    def test_one_mib_or_larger_is_rejected_from_header_without_body(self):
        for size in (1024 * 1024, 1024 * 1024 + 1, 2 ** 63):
            with self.subTest(size=size):
                self.assert_protocol_rejected(b"\x81\x7f" + struct.pack("!Q", size))

    def test_noncanonical_and_invalid_control_frames_rejected(self):
        for data in (b"\x81\x7e\x00\x01x", b"\x81\x7f" + struct.pack("!Q", 126),
                     frame(b"x" * 126, opcode=9), frame(b"x", opcode=8),
                     frame(struct.pack("!H", 1005), opcode=8)):
            with self.subTest(data=data):
                self.assert_protocol_rejected(data)

    def test_bad_text_and_event_envelopes_rejected_without_raw_output(self):
        for text in (b"\xff", b"not-json-private-session", b"[]", b"{}", b'{"event_type":[]}',
                     b'{"event_type":{"id":1,"data":{}}}'):
            with self.subTest(text=text):
                self.assert_protocol_rejected(frame(text))

    def test_disconnect_and_close_reset_proof(self):
        for chunk in (b"", frame(struct.pack("!H", 1000), opcode=8)):
            with self.subTest(chunk=chunk):
                self.connect()
                self.deliver(stream_frames())
                self.assertTrue(self.events.fresh_stream)
                with self.assertRaises(OSError):
                    self.deliver(chunk)
                self.assertFalse(self.events.fresh_stream)
                self.assertTrue(self.websocket.closed)

    def test_close_is_idempotent_and_reopen_needs_new_proof(self):
        self.connect()
        self.deliver(stream_frames())
        events = self.events
        events.close()
        events.close()
        self.assertFalse(events.fresh_stream)
        with self.assertRaises(OSError):
            events.wait(0)
        new_sockets = [FakeSocket(http()), FakeSocket(upgrade())]
        with patch.object(ae.socket, "create_connection", side_effect=new_sockets):
            events.open()
        self.assertFalse(events.fresh_stream)
        events.close()

    def test_failed_reopen_discards_previous_proof(self):
        self.connect()
        self.deliver(stream_frames())
        with patch.object(ae.socket, "create_connection", side_effect=ConnectionRefusedError()):
            with self.assertRaises(OSError):
                self.events.open()
        self.assertFalse(self.events.fresh_stream)

    def test_frame_budget_bounds_event_flood_with_frozen_test_clock(self):
        self.connect()
        self.deliver(event("Log", {"text": "x"}) * 1000, timeout=0.2)
        self.assertTrue(self.websocket.chunks or self.events._buffer)
        self.assertLess(self.websocket.recv_calls, 10)

    def test_invalid_timeout_and_port_are_rejected(self):
        for port in (0, 65536, -1, True, "8082"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                ae.Events(port=port)
        for timeout in (-1, float("nan"), float("inf"), True):
            events = ae.Events()
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                events.open(timeout)
        self.connect()
        for timeout in (-1, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.events.wait(timeout)


if __name__ == "__main__":
    unittest.main()
