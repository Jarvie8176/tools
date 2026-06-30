"""XDG-style per-user operator identity for MHL creator info (#11).

The MHL ``<creatorinfo>`` author / phone / role / location fields describe the
**operator**, not the job. When ``rmig init`` produces one TOML per job,
repeating those in every ``[defaults]`` is friction, and rotating the author
(new email, new role) means editing every file. This module adds a per-user
identity layer *below* per-job and ``[defaults]`` config — the same way
``~/.gitconfig`` sits below per-repo git config.

Resolution chain (highest wins):

    [[jobs]] field  >  [defaults] field  >  identity.toml  >  unset
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# Only these keys are honored — they mirror the four MHL identity fields on
# ``[defaults]``. Any other key in the file is ignored (forward-compatible).
IDENTITY_KEYS = (
    "mhl_author",
    "mhl_author_phone",
    "mhl_author_role",
    "mhl_location",
)

STARTER = """\
# rclone-migrate operator identity (#11).
# Per-user fallback for the MHL <creatorinfo> fields — used when a job / the
# config's [defaults] leave them unset. Honors $XDG_CONFIG_HOME.

mhl_author = "Your Name <you@example.com>"   # git-style "Name <email>"
mhl_author_role = "DIT"                       # e.g. DIT, Editor, Archivist
mhl_location = "Home Studio"
# mhl_author_phone = "+1-555-0100"            # rare
"""


class IdentityError(ValueError):
    pass


def identity_path() -> Path:
    """Resolve the identity file path, honoring ``XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return Path(base) / "rclone-migrate" / "identity.toml"


def load_identity(path: Optional[Path] = None) -> Dict[str, str]:
    """Return the identity dict (only ``IDENTITY_KEYS``), or ``{}`` if no file.

    Raises ``IdentityError`` on malformed TOML or a non-string value, so a typo
    surfaces loudly rather than silently dropping the operator's name from the
    chain of custody.
    """
    p = path or identity_path()
    if not p.exists():
        return {}
    try:
        with open(p, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise IdentityError(f"malformed identity file {p}: {e}") from e
    out: Dict[str, str] = {}
    for k in IDENTITY_KEYS:
        if k not in raw:
            continue
        val = raw[k]
        if not isinstance(val, str):
            raise IdentityError(
                f"identity file {p}: '{k}' must be a string, "
                f"got {type(val).__name__}"
            )
        out[k] = val
    return out


def write_starter(path: Optional[Path] = None, *, force: bool = False) -> Path:
    """Write a starter identity file. Refuses to clobber unless ``force``."""
    p = path or identity_path()
    if p.exists() and not force:
        raise IdentityError(
            f"identity file already exists: {p} (use --force to overwrite)"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(STARTER, encoding="utf-8")
    return p
