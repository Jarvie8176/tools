"""Per-user MHL operator identity (#11): identity.toml fallback below
[defaults] / per-job in the MHL creatorinfo resolution chain."""
from pathlib import Path

import pytest

from rclone_migrate import config as config_mod
from rclone_migrate import identity


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    """Point XDG_CONFIG_HOME at a temp dir so the real ~/.config is never read."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg" / "rclone-migrate" / "identity.toml"


def _write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ---- load_identity ----------------------------------------------------------

def test_identity_path_honors_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert identity.identity_path() == tmp_path / "cfg" / "rclone-migrate" / "identity.toml"


def test_identity_path_defaults_to_home_config(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/someone")
    assert identity.identity_path() == Path("/home/someone/.config/rclone-migrate/identity.toml")


def test_load_absent_returns_empty(xdg):
    assert identity.load_identity(xdg) == {}


def test_load_reads_known_keys_ignores_others(xdg):
    _write(xdg, """
        mhl_author = "Me <me@example.com>"
        mhl_author_role = "DIT"
        mhl_location = "Home Studio"
        something_else = "ignored"
    """)
    out = identity.load_identity(xdg)
    assert out == {
        "mhl_author": "Me <me@example.com>",
        "mhl_author_role": "DIT",
        "mhl_location": "Home Studio",
    }


def test_load_malformed_raises(xdg):
    _write(xdg, "this is = not valid = toml")
    with pytest.raises(identity.IdentityError) as e:
        identity.load_identity(xdg)
    assert "malformed" in str(e.value)


def test_load_non_string_value_raises(xdg):
    _write(xdg, "mhl_author = 42\n")
    with pytest.raises(identity.IdentityError) as e:
        identity.load_identity(xdg)
    assert "must be a string" in str(e.value)


# ---- write_starter ----------------------------------------------------------

def test_write_starter_creates_then_refuses_clobber(xdg):
    p = identity.write_starter(xdg)
    assert p.exists() and "mhl_author" in p.read_text()
    with pytest.raises(identity.IdentityError):
        identity.write_starter(xdg)            # refuses to overwrite
    identity.write_starter(xdg, force=True)    # ... unless forced
    # The starter round-trips through load (it's valid TOML).
    assert "mhl_author" in identity.load_identity(xdg)


# ---- config.load integration: resolution chain ------------------------------

def _cfg(tmp_path, defaults_block=""):
    cfg_path = tmp_path / "rmig.toml"
    cfg_path.write_text(
        f"{defaults_block}\n"
        "[[jobs]]\n"
        'name = "j"\n'
        'src = "/tmp/a"\n'
        'dst = "/tmp/b"\n',
        encoding="utf-8",
    )
    return config_mod.load(cfg_path)


def test_identity_fills_unset_defaults(xdg, tmp_path):
    _write(xdg, 'mhl_author = "Ident Me <id@example.com>"\nmhl_location = "Studio"\n')
    cfg = _cfg(tmp_path)  # no [defaults] author at all
    job = cfg.jobs[0]
    assert job.resolved_mhl_author(cfg.defaults) == "Ident Me <id@example.com>"
    assert job.resolved_mhl_location(cfg.defaults) == "Studio"


def test_defaults_override_identity(xdg, tmp_path):
    _write(xdg, 'mhl_author = "Ident Me <id@example.com>"\n')
    cfg = _cfg(tmp_path, '[defaults]\nmhl_author = "Config Author <cfg@example.com>"')
    job = cfg.jobs[0]
    # [defaults] wins over identity.toml.
    assert job.resolved_mhl_author(cfg.defaults) == "Config Author <cfg@example.com>"


def test_job_overrides_identity(xdg, tmp_path):
    _write(xdg, 'mhl_author = "Ident Me <id@example.com>"\n')
    cfg_path = tmp_path / "rmig.toml"
    cfg_path.write_text(
        "[[jobs]]\n"
        'name = "j"\n'
        'src = "/tmp/a"\n'
        'dst = "/tmp/b"\n'
        'mhl_author = "Job Author <job@example.com>"\n',
        encoding="utf-8",
    )
    cfg = config_mod.load(cfg_path)
    job = cfg.jobs[0]
    assert job.resolved_mhl_author(cfg.defaults) == "Job Author <job@example.com>"


def test_no_identity_no_default_is_none(xdg, tmp_path):
    cfg = _cfg(tmp_path)  # no identity file, no [defaults]
    job = cfg.jobs[0]
    assert job.resolved_mhl_author(cfg.defaults) is None
