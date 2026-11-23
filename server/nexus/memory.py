"""Keep the process inside small hosts (Render free: 512 MB).

pandas work frees lots of small objects, but glibc keeps freed memory mapped in per-thread
arenas, so RSS ratchets up after every heavy step. `trim()` hands free pages back to the OS
(Linux only; a no-op elsewhere). render.yaml also sets MALLOC_ARENA_MAX=2 to limit the arenas
the scheduler, wire and request threads create.
"""

from __future__ import annotations

import ctypes
import gc
import sys

_libc = None
if sys.platform.startswith("linux"):
    try:
        _libc = ctypes.CDLL("libc.so.6")
    except OSError:
        _libc = None


def trim() -> None:
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:
            pass

