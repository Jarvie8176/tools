"""Per-session OTel data plane: sidecar reader + OTLP sink (rollup, dechunk, PII strip, dedup)."""
import json
import os
import socket
import stat

from cc_monitor import otel, otel_sink


# --- OTLP JSON payload builders (mirror the real api_request log-event shape from the PoC) ---

def _val(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _kvs(d):
    return [{"key": k, "value": _val(v)} for k, v in d.items()]


def log_payload(*records, resource=None):
    """records = list of flat attribute dicts -> an ExportLogsServiceRequest."""
    return {"resourceLogs": [{
        "resource": {"attributes": _kvs(resource or {})},
        "scopeLogs": [{"logRecords": [{"attributes": _kvs(r)} for r in records]}],
    }]}


def api_request(sid, effort="high", seq=1, req="req_1", **extra):
    a = {"event.name": "api_request", "session.id": sid, "effort": effort,
         "event.sequence": seq, "request_id": req, "model": "claude-opus-4-8", "speed": "normal",
         "input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 500,
         "cache_creation_tokens": 0, "cost_usd": 0.02}
    a.update(extra)
    return a


# --- reader ---

def test_read_absent_returns_none(tmp_path):
    assert otel.read(str(tmp_path / "nope.json")) is None


def test_read_malformed_returns_none(tmp_path):
    p = tmp_path / "otel.json"
    p.write_text("{not json")
    assert otel.read(str(p)) is None


def test_read_non_object_returns_none(tmp_path):
    p = tmp_path / "otel.json"
    p.write_text("[1,2,3]")
    assert otel.read(str(p)) is None  # a top-level list is not a session map


def test_read_valid_returns_map(tmp_path):
    p = tmp_path / "otel.json"
    p.write_text(json.dumps({"sid1": {"effort": "high"}}))
    assert otel.read(str(p)) == {"sid1": {"effort": "high"}}


# --- Rollup ---

def test_ingest_extracts_effort_and_tokens(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    assert r.ingest_logs(log_payload(api_request("s1", effort="xhigh"))) == 1
    snap = r.snapshot()["s1"]
    assert snap["effort"] == "xhigh" and snap["model"] == "claude-opus-4-8"
    assert snap["tokens"] == {"input": 100, "output": 10, "cacheRead": 500, "cacheCreation": 0}
    assert snap["cost_usd"] == 0.02 and snap["api_requests"] == 1


def test_effort_latest_wins_by_sequence(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    r.ingest_logs(log_payload(api_request("s1", effort="low", seq=1, req="a")))
    r.ingest_logs(log_payload(api_request("s1", effort="max", seq=2, req="b")))
    assert r.snapshot()["s1"]["effort"] == "max"


def test_out_of_order_flush_does_not_regress_effort(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    r.ingest_logs(log_payload(api_request("s1", effort="max", seq=5, req="b")))
    r.ingest_logs(log_payload(api_request("s1", effort="low", seq=2, req="a")))  # older, arrives late
    assert r.snapshot()["s1"]["effort"] == "max"  # newer seq's effort retained


def test_cumulative_dedup_by_request_id(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    r.ingest_logs(log_payload(api_request("s1", req="dup", seq=1)))
    r.ingest_logs(log_payload(api_request("s1", req="dup", seq=1)))  # OTLP retry — must not double
    snap = r.snapshot()["s1"]
    assert snap["api_requests"] == 1 and snap["tokens"]["input"] == 100


def test_cumulative_sums_across_distinct_requests(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    r.ingest_logs(log_payload(api_request("s1", req="a", seq=1)))
    r.ingest_logs(log_payload(api_request("s1", req="b", seq=2)))
    snap = r.snapshot()["s1"]
    assert snap["api_requests"] == 2 and snap["tokens"]["input"] == 200
    assert round(snap["cost_usd"], 4) == 0.04


def test_pii_never_persisted(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    r.ingest_logs(log_payload(api_request("s1", **{
        "user.email": "op@example.com", "user.id": "u-1", "user.account_uuid": "acc-1",
        "organization.id": "org-1"})))
    blob = json.dumps(r.snapshot())
    for pii in ("op@example.com", "u-1", "acc-1", "org-1"):
        assert pii not in blob
    # also absent from the persisted file
    assert "example.com" not in (tmp_path / "o.json").read_text()


def test_non_api_request_ignored(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    rec = {"event.name": "user_prompt", "session.id": "s1", "prompt_length": 5}
    assert r.ingest_logs(log_payload(rec)) == 0
    assert r.snapshot() == {}


def test_missing_session_id_ignored(tmp_path):
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    rec = {"event.name": "api_request", "effort": "high"}  # no session.id
    assert r.ingest_logs(log_payload(rec)) == 0


def test_resource_level_session_id_used(tmp_path):
    # session.id can ride on the resource instead of the record; the merge must still find it
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    rec = {"event.name": "api_request", "effort": "high", "request_id": "r1",
           "input_tokens": 1, "output_tokens": 0, "cache_read_tokens": 0,
           "cache_creation_tokens": 0, "cost_usd": 0.0, "event.sequence": 1}
    r.ingest_logs(log_payload(rec, resource={"session.id": "s-res"}))
    assert "s-res" in r.snapshot()


def test_lru_bounds_session_count(tmp_path, monkeypatch):
    monkeypatch.setattr(otel_sink, "_MAX_SESSIONS", 3)
    r = otel_sink.Rollup(str(tmp_path / "o.json"))
    for i in range(5):
        r.ingest_logs(log_payload(api_request(f"s{i}", seq=1, req=f"r{i}")))
    snap = r.snapshot()
    assert len(snap) == 3 and set(snap) == {"s2", "s3", "s4"}  # oldest evicted


def test_sidecar_written_0600(tmp_path):
    p = tmp_path / "o.json"
    r = otel_sink.Rollup(str(p))
    r.ingest_logs(log_payload(api_request("s1")))
    mode = stat.S_IMODE(os.stat(p).st_mode)
    assert mode == 0o600  # holds per-session cost -> owner-only


# --- sink HTTP path (dechunk end-to-end) ---

def _chunked(body: bytes) -> bytes:
    return f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"


def _post(port, path, raw_body, headers):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        req = f"POST {path} HTTP/1.1\r\nHost: x\r\n"
        for k, v in headers.items():
            req += f"{k}: {v}\r\n"
        req += "\r\n"
        s.sendall(req.encode() + raw_body)
        s.settimeout(3)
        return s.recv(4096)
    finally:
        s.close()


def test_sink_dechunks_real_post(tmp_path):
    sink = otel_sink.OtelSink(port=0, path=str(tmp_path / "o.json"))
    assert sink.start()
    try:
        port = sink._httpd.server_address[1]
        body = json.dumps(log_payload(api_request("live1", effort="high"))).encode()
        resp = _post(port, "/v1/logs", _chunked(body),
                     {"Content-Type": "application/json", "Transfer-Encoding": "chunked"})
        assert b"200" in resp.split(b"\r\n", 1)[0]
        assert sink.rollup.snapshot()["live1"]["effort"] == "high"
    finally:
        sink.stop()


def test_sink_handles_gzip(tmp_path):
    import gzip
    sink = otel_sink.OtelSink(port=0, path=str(tmp_path / "o.json"))
    assert sink.start()
    try:
        port = sink._httpd.server_address[1]
        raw = gzip.compress(json.dumps(log_payload(api_request("gz1"))).encode())
        _post(port, "/v1/logs", _chunked(raw),
              {"Content-Type": "application/json", "Transfer-Encoding": "chunked",
               "Content-Encoding": "gzip"})
        assert "gz1" in sink.rollup.snapshot()
    finally:
        sink.stop()


def test_sink_non_json_dropped_not_fatal(tmp_path):
    sink = otel_sink.OtelSink(port=0, path=str(tmp_path / "o.json"))
    assert sink.start()
    try:
        port = sink._httpd.server_address[1]
        resp = _post(port, "/v1/logs", _chunked(b"\x08\x01not-protobuf-json"),
                     {"Content-Type": "application/x-protobuf", "Transfer-Encoding": "chunked"})
        assert b"200" in resp.split(b"\r\n", 1)[0]  # still 200 — exporter must not see a failure
        assert sink.rollup.snapshot() == {}
    finally:
        sink.stop()


def test_sink_metrics_endpoint_ignored(tmp_path):
    sink = otel_sink.OtelSink(port=0, path=str(tmp_path / "o.json"))
    assert sink.start()
    try:
        port = sink._httpd.server_address[1]
        body = json.dumps({"resourceMetrics": []}).encode()
        resp = _post(port, "/v1/metrics", _chunked(body),
                     {"Content-Type": "application/json", "Transfer-Encoding": "chunked"})
        assert b"200" in resp.split(b"\r\n", 1)[0]
        assert sink.rollup.snapshot() == {}  # log event is the sole source; metrics ignored
    finally:
        sink.stop()


def test_sink_bind_failure_best_effort(tmp_path):
    a = otel_sink.OtelSink(port=0, path=str(tmp_path / "a.json"))
    assert a.start()
    try:
        port = a._httpd.server_address[1]
        b = otel_sink.OtelSink(port=port, path=str(tmp_path / "b.json"))  # port already taken
        assert b.start() is False  # logged + degraded, not raised
    finally:
        a.stop()
