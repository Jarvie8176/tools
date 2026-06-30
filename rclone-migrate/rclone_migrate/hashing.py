"""Hash algorithm negotiation between two rclone endpoints."""
from __future__ import annotations

import hashlib
from typing import Iterable, List, Optional

from . import rclone


# Preference order: strongest first, with universally-supported fallbacks.
# Rclone uses lowercase names internally (matches `backend features --json` output).
PREFERRED_ORDER: List[str] = [
    "sha256",
    "sha1",
    "md5",
    "sha512",
    "blake3",
    # Backend-specific (only chosen if nothing else is shared)
    "dropbox",
    "quickxor",
    "whirlpool",
    "crc32",
    "xxh128",
    "xxh3",
]

# Hashes that Python's hashlib can compute locally without invoking rclone.
HASHLIB_SUPPORTED = {"md5", "sha1", "sha256", "sha512"}

# Streaming xxhash-family support via the optional `xxhash` package
# (install extra: rclone-migrate[xxhash]). hexdigests verified
# byte-identical to rclone's output: rclone "xxh3" == xxh3_64,
# "xxh128" == xxh3_128. "xxh64" has no rclone equivalent (rclone speaks
# xxh3/xxh128 only) so it *requires* this path.
try:  # pragma: no cover - import guard
    import xxhash as _xxhash

    _XXHASH_CTORS = {
        "xxh3": _xxhash.xxh3_64,
        "xxh128": _xxhash.xxh3_128,
        "xxh64": _xxhash.xxh64,
    }
except ImportError:  # pragma: no cover
    _xxhash = None
    _XXHASH_CTORS = {}


def can_stream_local(algo: str) -> bool:
    """True iff ``hash_file_local`` computes ``algo`` in-process with a
    chunk loop (so ``progress_cb`` fires per chunk). False means it shells
    out to a per-file ``rclone hashsum`` subprocess with no intra-file
    progress — callers should then meter at file granularity instead."""
    return algo in HASHLIB_SUPPORTED or algo in _XXHASH_CTORS


class HashNegotiationError(RuntimeError):
    pass


def supported_hashes(path: str) -> List[str]:
    """Return rclone-reported hash list for the backend serving `path` (lowercase).

    This is the rclone backend's *advertised* capability only. For what rmig
    can actually obtain for a path (which, for local paths, also covers algos
    rmig streams in-process), use `effective_supported`."""
    feats = rclone.backend_features(path)
    return [h.lower() for h in feats.get("Hashes", [])]


def local_streamable_algos() -> set:
    """Algos rmig computes itself for a *local* file — hashlib + the xxhash
    family (when the `xxhash` package is importable) — independent of what the
    rclone backend advertises."""
    return set(HASHLIB_SUPPORTED) | set(_XXHASH_CTORS)


def effective_supported(path: str) -> set:
    """Hashes rmig can actually obtain for `path`.

    Local path: the rclone backend's advertised set PLUS anything rmig streams
    in-process (`manifest._refresh_local` hashes local bytes itself via
    `hash_file_local`), so e.g. `xxh128` is available even though rclone's
    *local* backend doesn't advertise it.

    Remote path: strictly the backend's advertised set — rmig can't hash bytes
    it doesn't hold without downloading them (a separate, opt-in path), so the
    negotiation gate stays honest about what the remote can natively produce."""
    s = set(supported_hashes(path))
    if rclone.is_local(path):
        s |= local_streamable_algos()
    return s


def negotiate(
    src: str,
    dst: str,
    override: Optional[str] = None,
    *,
    priority: Optional[List[str]] = None,
) -> str:
    """Pick the best hash algorithm shared by both endpoints.

    `override` (case-insensitive) forces a specific algorithm; raises if either
    side can't provide it — rclone-advertised, or rmig-streamable for local
    sides (see `effective_supported`). Returns rclone's lowercase hash name.

    `priority` overrides the built-in PREFERRED_ORDER for this call (e.g.
    sourced from a profile). Items missing from the common set are skipped;
    fall back to PREFERRED_ORDER → any-common if `priority` exhausts.
    """
    src_h = effective_supported(src)
    dst_h = effective_supported(dst)

    if override:
        algo = override.lower()
        if algo not in src_h:
            raise HashNegotiationError(
                f"src ({src}) cannot provide hash '{algo}'. "
                f"Available: {sorted(src_h)}"
            )
        if algo not in dst_h:
            raise HashNegotiationError(
                f"dst ({dst}) cannot provide hash '{algo}'. "
                f"Available: {sorted(dst_h)}"
            )
        return algo

    common = src_h & dst_h
    if not common:
        raise HashNegotiationError(
            f"no common hash between src ({sorted(src_h)}) and dst ({sorted(dst_h)})"
        )

    if priority:
        for cand in priority:
            c = cand.strip().lower()
            if c in common:
                return c
        # Caller-supplied priority exhausted with no match — fall through to
        # PREFERRED_ORDER so we still return a usable algo, rather than fail.
    for cand in PREFERRED_ORDER:
        if cand in common:
            return cand
    return sorted(common)[0]


def hash_file_local(
    path: str,
    algo: str,
    chunk_size: int = 1 << 20,
    progress_cb=None,
) -> str:
    """Compute hash of a local file using hashlib if possible, else rclone.

    ``progress_cb``, if given, is called with the byte count of each chunk
    read so callers can drive a live throughput meter even while a single
    large file is being hashed.
    """
    if algo in HASHLIB_SUPPORTED:
        h = hashlib.new(algo)
    elif algo in _XXHASH_CTORS:
        h = _XXHASH_CTORS[algo]()
    else:
        h = None
    if h is not None:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
                if progress_cb is not None:
                    progress_cb(len(chunk))
        return h.hexdigest()
    # No local streaming impl (e.g. crc32/blake3/quickxor without a lib):
    # fall back to a per-file rclone hashsum subprocess.
    result = rclone.hashsum_file(algo, path)
    if result is None:
        raise HashNegotiationError(
            f"failed to hash {path} with algorithm '{algo}'"
        )
    return result


def normalize(algo: str) -> str:
    """Normalize user-typed hash names to rclone's lowercase form."""
    a = algo.strip().lower()
    # Common aliases
    return {
        "sha-1": "sha1",
        "sha-256": "sha256",
        "sha-512": "sha512",
    }.get(a, a)
