"""statusLine sample ingestion + the per-family window calibration built from it."""
from cc_monitor import statusline, window

OPUS_1M = "claude-opus-4-8[1m]"
FABLE_1M = "claude-fable-5[1m]"


def _cal(claude):
    return statusline.calibrate(claude.statusline_dir, claude.claude_json)


def test_absent_dir_yields_empty_calibration(claude):
    cal = _cal(claude)
    assert cal.sessions == {} and cal.families == {} and cal.one_m_seen is False


def test_sample_resolves_its_own_session(claude):
    claude.statusline("sid-a", win=1_000_000, model_id=OPUS_1M, effort="high")
    cal = _cal(claude)
    assert cal.sessions["sid-a"]["win"] == 1_000_000
    assert window.resolve({}, {}, "claude-opus-4-8", 0, False,
                          cal=cal, session_id="sid-a") == (1_000_000, True)


def test_sample_generalises_across_same_family(claude):
    # the point of the whole layer: an `sdk-cli` worker never renders a status line, so its window
    # comes from a TUI sibling's sample of the same family (single account, single host).
    claude.statusline("tui-sid", win=1_000_000, model_id=OPUS_1M)
    cal = _cal(claude)
    assert window.resolve({}, {}, "claude-opus-4-8", 0, False,
                          cal=cal, session_id="headless-sid") == (1_000_000, True)


def test_sample_does_not_generalise_across_families(claude):
    claude.statusline("tui-sid", win=1_000_000, model_id=OPUS_1M)
    cal = _cal(claude)
    # a sonnet session has no sample and no options entry -> still unknown, not silently 1M
    assert window.resolve({}, {}, "claude-sonnet-5", 0, False,
                          cal=cal, session_id="other") == (200_000, False)


def test_latest_sample_wins_per_family(claude):
    # entitlement can change (plan change, credits blocked); a stale 1M sample must not outvote a
    # fresh 200k one for the same family.
    claude.statusline("old", win=1_000_000, model_id=OPUS_1M, ts=100.0)
    claude.statusline("new", win=200_000, model_id="claude-opus-4-8", ts=200.0)
    cal = _cal(claude)
    assert cal.families["OPUS"] == 200_000
    assert window.resolve({}, {}, "claude-opus-4-8", 0, False,
                          cal=cal, session_id="third") == (200_000, True)


def test_proc_kill_switch_outranks_family_generalisation(claude):
    # the one per-worker fact that can legitimately contradict an account-level inference
    claude.statusline("tui-sid", win=1_000_000, model_id=OPUS_1M)
    cal = _cal(claude)
    env = {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}
    assert window.resolve(env, {}, "claude-opus-4-8", 0, False,
                          cal=cal, session_id="worker") == (200_000, True)


def test_peak_overrides_a_too_small_calibration(claude):
    # usage above the calibrated window is hard proof the calibration is stale
    claude.statusline("tui-sid", win=200_000, model_id="claude-opus-4-8")
    cal = _cal(claude)
    assert window.resolve({}, {}, "claude-opus-4-8", 400_000, False,
                          cal=cal, session_id="worker") == (1_000_000, True)


def test_model_options_supply_value_but_defer_certainty(claude):
    # ~/.claude.json names a suffixed fable id, but nothing has yet proven this account gets [1m]
    claude.model_options([FABLE_1M])
    cal = _cal(claude)
    assert cal.options == {"FABLE": 1_000_000} and cal.one_m_seen is False
    assert window.resolve({}, {}, "claude-fable-5", 0, False,
                          cal=cal, session_id="s") == (1_000_000, False)


def test_model_options_become_certain_once_a_sample_proves_1m(claude):
    # an Opus sample proves the account-level predicate is on; the fable option id is then trusted
    claude.model_options([FABLE_1M])
    claude.statusline("opus-sid", win=1_000_000, model_id=OPUS_1M)
    cal = _cal(claude)
    assert cal.one_m_seen is True
    assert window.resolve({}, {}, "claude-fable-5", 0, False,
                          cal=cal, session_id="s") == (1_000_000, True)


def test_malformed_sample_skipped_not_fatal(claude):
    import os
    claude.statusline("good", win=1_000_000, model_id=OPUS_1M)
    os.makedirs(claude.statusline_dir, exist_ok=True)
    with open(os.path.join(claude.statusline_dir, "bad.json"), "w") as fh:
        fh.write("{not json")
    cal = _cal(claude)
    assert cal.families["OPUS"] == 1_000_000 and "bad" not in cal.sessions


def test_effort_is_never_generalised(claude):
    claude.statusline("sid-a", win=1_000_000, model_id=OPUS_1M, effort="xhigh")
    cal = _cal(claude)
    assert statusline.effort_for(cal, "sid-a") == "xhigh"
    assert statusline.effort_for(cal, "sid-b") is None
