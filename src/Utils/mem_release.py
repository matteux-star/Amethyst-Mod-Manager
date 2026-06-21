"""Return freed heap pages to the OS after large UI teardowns.

CPython frees objects promptly, but glibc's allocator keeps the freed arenas
mapped for reuse, so RSS stays high even though the Python objects are gone
(confirmed via memtrace: object counts drop on panel close while RSS does not).
``malloc_trim(0)`` asks glibc to release that free top-of-heap memory back to the
OS. This is purely an RSS hygiene call — it never affects correctness, and it is
a safe no-op on non-glibc platforms (musl, macOS, Windows).

Call ``release_memory()`` after destroying a heavy, repeatedly-opened panel
(Nexus browser, Collections, big overlays).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc

_libc = None
_resolved = False


def _get_libc():
    global _libc, _resolved
    if _resolved:
        return _libc
    _resolved = True
    try:
        # Only glibc exposes malloc_trim. ctypes.util.find_library keeps us off
        # musl (which has no malloc_trim symbol and would raise on access).
        name = ctypes.util.find_library("c")
        lib = ctypes.CDLL(name) if name else ctypes.CDLL("libc.so.6")
        if hasattr(lib, "malloc_trim"):
            lib.malloc_trim.argtypes = [ctypes.c_size_t]
            lib.malloc_trim.restype = ctypes.c_int
            _libc = lib
    except Exception:
        _libc = None
    return _libc


def release_memory() -> None:
    """gc.collect() then malloc_trim(0). Safe no-op where unsupported."""
    try:
        gc.collect()
    except Exception:
        pass
    lib = _get_libc()
    if lib is not None:
        try:
            lib.malloc_trim(0)
        except Exception:
            pass
