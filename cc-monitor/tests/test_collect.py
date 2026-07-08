import time

from cc_monitor import collect, render

from .conftest import assistant, custom_title, user


def test_discovers_both_populations(claude):
    # a --resume worker (registry has FRESH status) + an env-spawned worker (no status)
    fresh = int((time.time() + 3600) * 1000)  # statusUpdatedAt newer than transcript activity
    claude.registry(101, "res-uuid", "/home/x/p", name="cc-01", status="idle",
                    bridge="session_res", status_updated_at=fresh)
    claude.proc_alive(101, {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"})
    claude.transcript("res-uuid", "/home/x/p", [
        custom_title("SSH manifest epic"),
        assistant("claude-opus-4-8", inp=300_000),
    ])
    claude.registry(202, "env-uuid", "/home/x/p", name="cc-02")  # env-spawned, no status
    claude.proc_alive(202, {})
    claude.transcript("env-uuid", "/home/x/p", [
        user("go P2"),
        assistant("claude-opus-4-8", inp=120_000),
    ])
    d = collect.collect(now=time.time())
    by_id = {r["u8"]: r for r in d["rows"]}
    assert set(by_id) == {"res-uuid"[:8], "env-uuid"[:8]}
    # env-spawned worker with recent activity is busy via mtime heuristic
    assert by_id["env-uuid"[:8]]["status"] == "busy"
    assert by_id["res-uuid"[:8]]["status"] == "idle"  # authoritative from registry


def test_stale_registry_entry_skipped(claude):
    claude.registry(303, "dead-uuid", "/home/x/p")  # no proc created -> not alive
    assert collect.collect()["rows"] == []


def test_window_1m_via_peak_lower_bound(claude):
    claude.registry(404, "u", "/home/x/p")
    claude.proc_alive(404, {})  # env readable, no [1m]
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=400_000)])
    row = collect.collect()["rows"][0]
    assert (row["win"], row["win_certain"]) == (1_000_000, True)


def test_resume_worker_window_from_settings_env_not_proc(claude):
    # regression: a `claude --resume` worker's /proc environ lacks ANTHROPIC_DEFAULT_OPUS_MODEL
    # (settings.json env is applied internally, not in /proc). Reading /proc alone under-reported
    # it as 200k; the settings.json env block must supply [1m] -> 1M, even below the 200k peak.
    claude.settings({"env": {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}})
    claude.registry(410, "u", "/home/x/p")
    claude.proc_alive(410, {})  # empty exec env, like a resume worker
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=61_000)])
    row = collect.collect()["rows"][0]
    assert (row["win"], row["win_certain"]) == (1_000_000, True)


def test_default_200k_when_no_proc_and_no_settings_1m(claude):
    # no [1m] anywhere (proc empty, settings has no env) -> genuinely 200k, and certain
    claude.registry(411, "u", "/home/x/p")
    claude.proc_alive(411, {})
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=50_000)])
    row = collect.collect()["rows"][0]
    assert (row["win"], row["win_certain"]) == (200_000, True)


def test_title_precedence_override_beats_custom(claude):
    claude.registry(505, "u", "/home/x/p", bridge="session_b")
    claude.proc_alive(505, {})
    claude.transcript("u", "/home/x/p", [custom_title("local title"),
                                         assistant("claude-opus-4-8", inp=10)])
    claude.titles({"u": "override wins"})
    row = collect.collect()["rows"][0]
    assert collect.title_of(row) == ("override wins", "override")


def test_title_cloud_side_when_no_local(claude):
    claude.registry(606, "u", "/home/x/p")
    claude.proc_alive(606, {})
    claude.transcript("u", "/home/x/p", [user("hi"), assistant("claude-opus-4-8", inp=10)])
    row = collect.collect()["rows"][0]
    assert collect.title_of(row) == ("", "cloud-side")


def test_render_smoke(claude):
    claude.registry(707, "u", "/home/x/p", status="busy")
    claude.proc_alive(707, {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"})
    claude.transcript("u", "/home/x/p", [custom_title("T"), assistant("claude-opus-4-8", inp=500)])
    d = collect.collect()
    assert "cc-monitor" in render.render_text(d)
    assert "<table>" in render.render_html(d)


def test_collect_surfaces_effort_from_settings(claude):
    claude.settings({"effortLevel": "high"})
    claude.registry(700, "u", "/home/x/p")
    claude.proc_alive(700, {})
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=10)])
    d = collect.collect()
    assert d["effort"] == "high"


def test_collect_effort_none_when_no_settings(claude):
    # no settings.json in the hermetic tree -> effort None (render shows '?')
    d = collect.collect()
    assert d["effort"] is None


def test_collect_surfaces_initial_prompt_per_row(claude):
    claude.registry(701, "u", "/home/x/p")
    claude.proc_alive(701, {})
    claude.transcript("u", "/home/x/p", [user("open the epic"),
                                         assistant("claude-opus-4-8", inp=10),
                                         user("keep going")])
    row = collect.collect()["rows"][0]
    assert row["initial_prompt"] == "open the epic" and row["last_prompt"] == "keep going"


def test_pid_reuse_skipped_via_procstart(claude):
    # registry says the process started at tick 999, but the live PID started at 111 -> reused
    claude.registry(808, "u", "/home/x/p", procstart="999")
    claude.proc_alive(808, {}, starttime="111")
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=10)])
    assert collect.collect()["rows"] == []


def test_stale_idle_status_falls_through_to_activity(claude):
    # status says idle but statusUpdatedAt is days older than a just-written transcript -> not trusted
    claude.registry(909, "u", "/home/x/p", status="idle", status_updated_at=1)  # ~epoch 0
    claude.proc_alive(909, {})
    claude.transcript("u", "/home/x/p", [user("hi"), assistant("claude-opus-4-8", inp=10)])
    # fresh transcript -> activity heuristic -> busy, despite the stale 'idle'
    assert collect.collect(now=time.time())["rows"][0]["status"] == "busy"


def test_transcript_race_does_not_crash_collect(claude):
    # registry points at a transcript path that does not exist -> parse returns empty, no raise
    claude.registry(111, "ghost-uuid", "/home/x/p")
    claude.proc_alive(111, {})
    # no transcript written for ghost-uuid
    d = collect.collect()
    assert len(d["rows"]) == 1 and d["rows"][0]["ctx"] == 0


def test_status_no_timestamp_trusts_registry():
    # regression: a busy status with no statusUpdatedAt (status_ts=0) must NOT be downgraded to idle
    assert collect._status("busy", 0, 1000.0, 5000, 12) == "busy"
    assert collect._status("idle", 0, 1000.0, 1, 12) == "idle"
    # a stale idle (timestamp older than activity) still falls through to the activity heuristic
    assert collect._status("idle", 1.0, 1000.0, 1, 12) == "busy"


def test_parse_cache_reuses_unchanged_transcript(claude, monkeypatch):
    claude.registry(1, "u", "/home/x/p")
    claude.proc_alive(1, {})
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=10)])
    collect._PARSE_CACHE.clear()
    calls = []
    real = collect.transcript.parse
    monkeypatch.setattr(collect.transcript, "parse", lambda p: calls.append(p) or real(p))
    collect.collect()
    collect.collect()
    assert len(calls) == 1  # second collect served from cache (transcript unchanged)


def test_render_text_strips_ansi_control_chars(claude):
    claude.registry(1, "u", "/home/x/p")
    claude.proc_alive(1, {})
    claude.transcript("u", "/home/x/p", [user("\x1b]0;PWN\x07hi\x1b[2J"),
                                         assistant("claude-opus-4-8", inp=10)])
    out = render.render_text(collect.collect())
    assert "\x1b" not in out and "\x07" not in out and "PWN" in out


def test_render_escapes_xss_in_name_model_bridge(claude):
    claude.registry(222, "u", "/home/x/p", name="<script>x</script>", bridge="session_<b>")
    claude.proc_alive(222, {})
    claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8<img>", inp=10)])
    html = render.render_html(collect.collect())
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img>" not in html  # model escaped too


def test_busy_idle_gap_env_override(monkeypatch, tmp_path):
    # BUSY_IDLE_GAP now lives in config; the env var is the ops escape hatch (highest precedence).
    from cc_monitor import config
    cfgfile = str(tmp_path / "cfg.json")
    monkeypatch.setenv("CC_MONITOR_BUSY_IDLE_GAP", "45")
    config._cache[0] = None
    assert config.load(cfgfile)["busy_idle_gap"] == 45
    monkeypatch.setenv("CC_MONITOR_BUSY_IDLE_GAP", "not-a-number")
    config._cache[0] = None
    assert config.load(cfgfile)["busy_idle_gap"] == 12  # invalid -> default


def test_proc_liveness_classifies_gone_orphaned_alive(claude):
    claude.proc_alive(500, starttime="900", state="S")   # normal
    claude.proc_alive(501, starttime="900", state="Z")   # defunct
    assert collect._proc_liveness(500, "900") == "alive"
    assert collect._proc_liveness(501, "900") == "orphaned"
    assert collect._proc_liveness(500, "999") == "gone"   # procStart mismatch = PID reuse
    assert collect._proc_liveness(99999, None) == "gone"  # no such process


def test_orphaned_session_shown_as_orphaned_not_idle(claude):
    # a defunct worker: /proc still lists it (starttime matches) but state is Z. Its transcript
    # went silent, so the mtime heuristic would say "idle" — it must show "orphaned" instead.
    claude.registry(600, "zsid", "/home/x/p", name="cc-z", procstart="42")
    claude.proc_alive(600, starttime="42", state="Z")
    claude.transcript("zsid", "/home/x/p", [assistant("claude-opus-4-8", inp=1000)])
    rows = collect.collect()["rows"]
    z = [r for r in rows if r["session_id"] == "zsid"]
    assert len(z) == 1 and z[0]["status"] == "orphaned"  # surfaced, not filtered, not "idle"
