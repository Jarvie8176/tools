"""CLI surface: --version prints the package version; --redact/--no-redact set the per-invocation
privacy override (highest precedence, not persisted) for the render subcommands."""
import pytest

from cc_monitor import cli, config


def test_version_prints_package_version_and_exits_zero(capsys):
    # `cc-monitor --version` prints the package version and exits 0 (argparse `action=version`)
    with pytest.raises(SystemExit) as ex:
        cli.build_parser().parse_args(["--version"])
    assert ex.value.code == 0
    out = capsys.readouterr().out
    assert out.strip() == "0.1.0"


def test_pkg_version_is_0_1_0():
    assert cli._pkg_version() == "0.1.0"


def _run(argv):
    """Drive main() with collect/serve/render stubbed so only the override wiring is exercised."""
    return cli.main(argv)


def test_no_redact_flag_disables_redaction(monkeypatch):
    monkeypatch.setattr(cli, "collect", lambda *a, **k: {"ts": 0, "prom": {}, "rows": []})
    monkeypatch.setattr(cli, "render_text", lambda d: "")
    assert _run(["once", "--no-redact"]) == 0
    assert config.load()["redact_default"] is False   # explicit --no-redact wins


def test_redact_flag_forces_redaction(monkeypatch, tmp_path):
    # even with a config file that turns redaction OFF, --redact overrides it back on
    monkeypatch.setattr(config.paths, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    config.save({"redact_default": False})
    config._cache[0] = None
    monkeypatch.setattr(cli, "collect", lambda *a, **k: {"ts": 0, "prom": {}, "rows": []})
    monkeypatch.setattr(cli, "render_text", lambda d: "")
    assert _run(["once", "--redact"]) == 0
    assert config.load()["redact_default"] is True    # explicit --redact wins over the file


def test_no_flag_leaves_config_to_decide(monkeypatch, tmp_path):
    # without a flag, the override is a no-op -> the safe-by-default (True) stands
    monkeypatch.setattr(config.paths, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.setattr(cli, "collect", lambda *a, **k: {"ts": 0, "prom": {}, "rows": []})
    monkeypatch.setattr(cli, "render_text", lambda d: "")
    assert _run(["once"]) == 0
    assert config.load()["redact_default"] is True


def test_redact_and_no_redact_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["once", "--redact", "--no-redact"])
