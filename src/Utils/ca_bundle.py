"""
ca_bundle.py
Resolve a usable TLS CA bundle for HTTPS requests.

Why this exists
---------------
The AppImage/Flatpak bundles its own ``certifi`` CA file, but a user's
environment can override or break it:
  * a stray ``SSL_CERT_FILE`` / ``REQUESTS_CA_BUNDLE`` pointing at a missing
    or stale file (the classic "curl works, app doesn't" SSLError);
  * the bundled certifi failing to extract / being unreadable on their mount.

``resolve_ca_bundle()`` returns the first CA file that actually exists, in
priority order: an explicitly-set (and valid) env override → bundled certifi →
the system trust store. Pass the result as ``verify=`` to ``requests``.
"""

from __future__ import annotations

import os

from Utils.app_log import app_log

# Common system trust stores across distros (Arch/SteamOS, Debian, Fedora, …)
_SYSTEM_CA_PATHS = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/ssl/cert.pem",
)

_cached: str | None = None
_resolved: bool = False


def resolve_ca_bundle() -> str | None:
    """Return a path to a readable CA bundle, or None to use requests' default."""
    global _cached, _resolved
    if _resolved:
        return _cached

    _resolved = True
    chosen: str | None = None
    reason = ""

    # 1. Honour an explicit env override only if it actually points at a real file.
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        val = os.environ.get(var)
        if val:
            if os.path.isfile(val) and os.access(val, os.R_OK):
                chosen, reason = val, f"env {var}"
                break
            app_log(f"ca_bundle: ignoring {var}={val!r} (file missing/unreadable)")

    # 2. Bundled certifi, if its cacert.pem is present and readable.
    if chosen is None:
        try:
            import certifi
            where = certifi.where()
            if os.path.isfile(where) and os.access(where, os.R_OK):
                chosen, reason = where, "certifi"
            else:
                app_log(f"ca_bundle: certifi bundle missing/unreadable at {where!r}")
        except Exception as exc:
            app_log(f"ca_bundle: certifi unavailable: {exc!r}")

    # 3. Fall back to the system trust store.
    if chosen is None:
        for p in _SYSTEM_CA_PATHS:
            if os.path.isfile(p) and os.access(p, os.R_OK):
                chosen, reason = p, "system store"
                break

    if chosen is None:
        app_log("ca_bundle: no usable CA bundle found; using requests' default")
    else:
        app_log(f"ca_bundle: using {reason} -> {chosen}")
    _cached = chosen
    return chosen
