"""Bridge legacy ``WASELLER_*`` and new ``WAPSELL_*`` env prefixes.

The rebrand moved the env prefix from ``WASELLER_`` to ``WAPSELL_``. Code now
reads ``WAPSELL_*``, but production still ships ``WASELLER_*`` until the VPS env
is migrated. Mirror both directions with ``setdefault`` (an explicitly set value
always wins) so old deploys keep working during the transition. Imported for its
side effect from ``wapsell/__init__``; drop once every environment uses
``WAPSELL_*``.
"""

from __future__ import annotations

import os


def apply() -> None:
    """Mirror ``WASELLER_*`` <-> ``WAPSELL_*`` env vars without overwriting."""
    for key, val in list(os.environ.items()):
        if key.startswith("WASELLER_"):
            os.environ.setdefault("WAPSELL_" + key[len("WASELLER_") :], val)
        elif key.startswith("WAPSELL_"):
            os.environ.setdefault("WASELLER_" + key[len("WAPSELL_") :], val)


apply()
