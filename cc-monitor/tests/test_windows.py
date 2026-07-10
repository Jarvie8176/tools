"""Declared window map: load contract, and the mechanized prefill behind `models --detect`."""
from cc_monitor import windows

OPUS = "claude-opus-4-8"
HAIKU = "claude-haiku-4-5-20251001"
FABLE_1M = "claude-fable-5[1m]"


def test_absent_file_yields_empty_map(claude):
    assert windows.load(claude.windows_file) == {}


def test_null_and_junk_values_are_dropped(claude):
    # `null` is the prefill's "undecided" marker; it must never read as a declaration.
    claude.windows({OPUS: 1_000_000, HAIKU: None, "a": "1000000", "b": 0, "c": -5, "d": True})
    assert windows.load(claude.windows_file) == {OPUS: 1_000_000}


def test_save_preserves_nulls_for_the_operator(claude):
    windows.save({OPUS: 1_000_000, HAIKU: None}, claude.windows_file)
    with open(claude.windows_file) as fh:
        assert '"claude-haiku-4-5-20251001": null' in fh.read()
    assert windows.load(claude.windows_file) == {OPUS: 1_000_000}  # but load still hides it


# --- suggest(): the evidence rules ---


def test_peak_above_baseline_is_evidence():
    assert windows.suggest({OPUS: 400_000}, {}, {}) == {OPUS: 1_000_000}


def test_peak_below_baseline_is_not_evidence():
    # a 29k peak says nothing: the model could be a baseline model, or a 1M one that never filled.
    assert windows.suggest({HAIKU: 29_402}, {}, {}) == {HAIKU: None}


def test_peak_at_baseline_boundary_is_not_evidence():
    assert windows.suggest({OPUS: 200_000}, {}, {}) == {OPUS: None}


def test_model_options_resolve_a_family_with_no_peak_evidence():
    # Claude Code's own cache names the suffixed id it offers -> the window, without any usage
    assert windows.suggest({"claude-fable-5": 10}, {"FABLE": 1_000_000}, {}) == {
        "claude-fable-5": 1_000_000}


def test_existing_declaration_is_never_overwritten():
    # detect must not silently "fix" a value the operator chose, even when the peak disagrees
    assert windows.suggest({OPUS: 900_000}, {}, {OPUS: 200_000}) == {OPUS: 200_000}


def test_peak_beyond_every_known_window_stays_undecided():
    # we have proven a floor we cannot name a tier for -> the operator decides
    assert windows.suggest({OPUS: 1_500_000}, {}, {}) == {OPUS: None}


def test_promotion_uses_a_declared_tier_not_a_constant():
    assert windows.suggest({OPUS: 300_000}, {}, {"other": 500_000}) == {OPUS: 500_000}


# --- observed_peaks() / detect() over a real transcript tree ---


def test_observed_peaks_folds_input_side_across_transcripts(claude):
    from .conftest import assistant
    claude.transcript("s1", "/home/x/p", [assistant(OPUS, inp=10, cache_read=250_000)])
    claude.transcript("s2", "/home/x/p", [assistant(OPUS, inp=5)])
    claude.transcript("s3", "/home/x/q", [assistant(HAIKU, inp=100)])
    peaks = windows.observed_peaks(claude.projects)
    assert peaks == {OPUS: 250_010, HAIKU: 100}


def test_detect_prefills_from_peaks_and_options(claude):
    from .conftest import assistant
    claude.transcript("s1", "/home/x/p", [assistant(OPUS, inp=400_000)])
    claude.transcript("s2", "/home/x/p", [assistant("claude-fable-5", inp=10)])
    claude.transcript("s3", "/home/x/p", [assistant(HAIKU, inp=10)])
    claude.model_options([FABLE_1M])
    got = windows.detect(claude.projects, claude.claude_json, claude.windows_file)
    assert got == {OPUS: 1_000_000, "claude-fable-5": 1_000_000, HAIKU: None}


def test_detect_ignores_non_claude_models(claude):
    from .conftest import assistant
    claude.transcript("s1", "/home/x/p", [assistant("my-org/custom-llm", inp=400_000)])
    assert windows.observed_peaks(claude.projects) == {}


def test_detect_survives_a_malformed_transcript_line(claude):
    from .conftest import assistant
    path = claude.transcript("s1", "/home/x/p", [assistant(OPUS, inp=400_000)])
    with open(path, "a") as fh:
        fh.write("{not json\n")
    assert windows.observed_peaks(claude.projects) == {OPUS: 400_000}
