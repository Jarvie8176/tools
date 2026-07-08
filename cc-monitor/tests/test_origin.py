"""Session provenance: origin derivation from the .url ledger + entrypoint, the
reconciliation falloff, and its surfacing in the API payload / metrics / renderers."""
import json

from cc_monitor import ccsession, collect, config, metrics, render, stream, webui

from .conftest import assistant


def _live(claude, pid, sid, entrypoint=None, bridge=None):
    claude.registry(pid, sid, "/home/x/p", name=f"cc-{pid}", entrypoint=entrypoint, bridge=bridge)
    claude.proc_alive(pid, {})
    claude.transcript(sid, "/home/x/p", [assistant("claude-opus-4-8", inp=100)])


# --- ledger parsing -----------------------------------------------------------------------------
def test_managed_ledger_extracts_uuid8_and_excludes_non_workers(claude):
    claude.managed(["83464b3e", "e5ac998a"])                      # claude-tp-<uuid8>-<hash>.url
    open(f"{claude.ccsession}/claude.url", "w").close()           # RC's own — no uuid, excluded
    open(f"{claude.ccsession}/cc-20260707-2-1-197.url", "w").close()  # supervisor inst — excluded
    assert ccsession.managed_ledger(claude.ccsession) == {"83464b3e", "e5ac998a"}


def test_managed_ledger_uuid8_is_second_last_segment_even_with_dashed_host(claude):
    # host containing dashes must not shift the uuid8 (taken from the END)
    open(f"{claude.ccsession}/claude-my-host-abcd1234-9f9f9f.url", "w").close()
    assert ccsession.managed_ledger(claude.ccsession) == {"abcd1234"}


def test_managed_ledger_empty_when_no_ccsession(claude):
    assert ccsession.managed_ledger(claude.ccsession) == set()


# --- origin derivation --------------------------------------------------------------------------
def test_origin_managed_beats_entrypoint(claude):
    _live(claude, 1, "83464b3e-aaaa", entrypoint="sdk-cli")       # sdk-cli BUT ledger-managed
    claude.managed(["83464b3e"])
    row = collect.collect()["rows"][0]
    assert row["origin"] == "cc-session-managed" and row["managed"] is True


def test_origin_rc_env_spawned_from_sdk_cli(claude):
    _live(claude, 2, "aaaaaaaa-bbbb", entrypoint="sdk-cli")       # not in ledger
    row = collect.collect()["rows"][0]
    assert row["origin"] == "rc-env-spawned" and row["managed"] is False


def test_origin_individual_cli_from_cli_entrypoint(claude):
    _live(claude, 3, "cccccccc-dddd", entrypoint="cli")
    assert collect.collect()["rows"][0]["origin"] == "individual-cli"


def test_origin_individual_cli_default_when_no_entrypoint(claude):
    _live(claude, 4, "eeeeeeee-ffff")                             # no entrypoint field
    assert collect.collect()["rows"][0]["origin"] == "individual-cli"


def test_bridged_flag_tracks_bridge_id(claude):
    _live(claude, 5, "11111111-2222", entrypoint="sdk-cli", bridge="session_abc")
    row = collect.collect()["rows"][0]
    assert row["bridged"] is True and row["bridge_id"] == "session_abc"


# --- reconciliation -----------------------------------------------------------------------------
def test_recon_counts_falloff_and_scraped(claude):
    _live(claude, 1, "83464b3e-aaaa", entrypoint="sdk-cli"); claude.managed(["83464b3e", "01WydqvW"])
    _live(claude, 2, "aaaaaaaa-bbbb", entrypoint="sdk-cli")       # rc-env-spawned
    _live(claude, 3, "cccccccc-dddd", entrypoint="cli")          # individual-cli
    claude.ccprom({"workers": 7, "capacity": 32, "rc_connected": 0, "auth_healthy": 1})
    rc = collect.collect()["recon"]
    assert rc["registry"] == 3 and rc["managed"] == 1
    assert rc["rc_env_spawned"] == 1 and rc["individual_cli"] == 1
    assert rc["url_ledger"] == 2                                  # ledger has a stale entry (01Wyd…)
    assert rc["scraped"] == "7"                                   # the unreliable tmux scrape, verbatim


def test_recon_scraped_none_when_standalone(claude):
    _live(claude, 1, "aaaaaaaa-bbbb", entrypoint="cli")          # no cc-session on host
    rc = collect.collect()["recon"]
    assert rc["scraped"] is None and rc["url_ledger"] == 0


# --- payload / metrics / render surfacing -------------------------------------------------------
def test_serialize_payload_carries_origin_and_recon(claude):
    config.set_overrides(redact_default=False)
    _live(claude, 2, "aaaaaaaa-bbbb", entrypoint="sdk-cli")
    payload = json.loads(stream.serialize(collect.collect()))
    s = payload["sessions"][0]
    assert s["origin"] == "rc-env-spawned" and s["managed"] is False and "bridged" in s
    assert payload["recon"]["registry"] == 1


def test_metrics_emit_origin_and_ledger_gauges(claude):
    _live(claude, 1, "83464b3e-aaaa", entrypoint="sdk-cli"); claude.managed(["83464b3e"])
    claude.ccprom({"workers": 5, "rc_connected": 1, "auth_healthy": 1})
    expo = metrics.render_exposition(collect.collect())
    assert 'cc_monitor_sessions_by_origin{origin="cc-session-managed"} 1' in expo
    assert 'cc_monitor_sessions_by_origin{origin="individual-cli"} 0' in expo   # 0-series still emitted
    assert "cc_monitor_url_ledger 1" in expo and "cc_monitor_scraped_workers 5" in expo
    # HELP/TYPE appear exactly once per family (node-exporter rejects the file otherwise)
    assert expo.count("# TYPE cc_monitor_sessions_by_origin gauge") == 1


def test_render_text_and_html_show_origin_and_recon(claude):
    config.set_overrides(redact_default=False)
    _live(claude, 1, "83464b3e-aaaa", entrypoint="sdk-cli"); claude.managed(["83464b3e"])
    claude.ccprom({"workers": 3, "rc_connected": 1, "auth_healthy": 1})
    d = collect.collect()
    txt = render.render_text(d)
    assert "mgd" in txt and "recon: registry 1" in txt and "url-ledger 1" in txt
    html = render.render_html(d)
    assert "<th>origin</th>" in html and "url-ledger 1" in html


def test_spa_surfaces_origin_and_reconciliation():
    p = webui.spa_page().decode()
    assert "data-sort=origin" in p and "originAbbr" in p          # origin column + sort
    assert "grouporigin" in p and "group by origin" in p         # REAL origin grouping…
    assert "group bridged" not in p                              # …replacing the bridged proxy
    assert "paintRecon" in p and "id=recon" in p                 # reconciliation strip
