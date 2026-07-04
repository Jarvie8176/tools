import time

from cc_monitor import collect, render

from .conftest import assistant, custom_title, user


def test_discovers_both_populations(claude):
    # a --resume worker (registry has status) + an env-spawned worker (no status)
    claude.registry(101, "res-uuid", "/home/x/p", name="cc-01", status="idle",
                    bridge="session_res")
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
