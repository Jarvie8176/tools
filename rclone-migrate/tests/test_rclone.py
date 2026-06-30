"""Tests for the rclone subprocess wrapper `_run` — focused on stderr
capture/auditability (#52). These monkeypatch subprocess.run so they never
require an actual rclone binary."""
import subprocess

import pytest

from rclone_migrate import rclone


@pytest.fixture(autouse=True)
def _stub_bin(monkeypatch):
    monkeypatch.setattr(rclone, "_bin", lambda: "rclone")
    # Verbose hook off by default (each test sets it as needed).
    monkeypatch.setattr(rclone, "_VERBOSE_HOOK", None)


def _fake_run(returncode=0, stderr="", record=None):
    def run(full, **kw):
        if record is not None:
            record["stdout"] = kw.get("stdout")
            record["stderr_arg"] = kw.get("stderr")
            record["argv"] = full
        return subprocess.CompletedProcess(full, returncode, stdout=None, stderr=stderr)
    return run


def test_run_always_pipes_stderr_even_capture_false(monkeypatch):
    """#52: with capture=False (stdout streams live for a long copy), stderr
    is STILL piped so rclone's diagnostics can be captured, while stdout is
    left inherited for live progress."""
    rec = {}
    monkeypatch.setattr(rclone.subprocess, "run",
                        _fake_run(returncode=0, stderr="", record=rec))
    rclone._run(["copyto", "a", "b"], capture=False)
    assert rec["stderr_arg"] is subprocess.PIPE   # stderr captured
    assert rec["stdout"] is None                  # stdout still streamed live


def test_run_capture_true_pipes_both(monkeypatch):
    rec = {}
    monkeypatch.setattr(rclone.subprocess, "run",
                        _fake_run(returncode=0, stderr="", record=rec))
    rclone._run(["lsf", "x"], capture=True)
    assert rec["stdout"] is subprocess.PIPE
    assert rec["stderr_arg"] is subprocess.PIPE


def test_run_failure_preserves_stderr_in_error(monkeypatch):
    """The decisive cause must ride along on RcloneError — even capture=False,
    where the prior code left cp.stderr=None and the message blank (#52)."""
    monkeypatch.setattr(rclone.subprocess, "run",
                        _fake_run(returncode=1, stderr="ERROR : errno -1\n"))
    with pytest.raises(rclone.RcloneError) as exc:
        rclone._run(["copyto", "a", "b"], capture=False)
    assert "errno -1" in str(exc.value)
    assert "exit 1" in str(exc.value)


def test_run_capture_false_echoes_stderr_to_sys_stderr(monkeypatch, capsys):
    """On success-with-warnings, withheld stderr is echoed via sys.stderr so
    the user still sees it AND audit.run()'s _Tee records it to the log."""
    monkeypatch.setattr(rclone.subprocess, "run",
                        _fake_run(returncode=0, stderr="NOTICE: skipped 1 file\n"))
    rclone._run(["copyto", "a", "b"], capture=False)
    err = capsys.readouterr().err
    assert "skipped 1 file" in err


def test_run_capture_true_does_not_echo_stderr(monkeypatch, capsys):
    """capture=True callers consume cp.stderr themselves; _run must not also
    echo it (would double-print). Behaviour preserved from before #52."""
    cp = None
    monkeypatch.setattr(rclone.subprocess, "run",
                        _fake_run(returncode=0, stderr="NOTICE: warn\n"))
    cp = rclone._run(["lsf", "x"], capture=True)
    err = capsys.readouterr().err
    assert "warn" not in err              # not echoed
    assert "warn" in cp.stderr            # but available to the caller
