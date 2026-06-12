"""Structural log filter — masks secrets before records hit any handler.

Logs leak. They get tailed to disk, shipped to S3, mirrored to a vendor SaaS,
indexed by ELK, and grep-pasted into Slack. The blast radius of an accidental
``log.info("config: %s", os.environ)`` is everything.

This filter intercepts every :class:`logging.LogRecord` at the boundary and
rewrites both the formatted message and string args, replacing matches of any
configured regex with ``<redacted>``. It is *structural* (not opt-in per
call-site) so a new ``log.info`` added next month is automatically covered.

Defaults catch: ``OPENROUTER_API_KEY``, ``META_APP_SECRET``, any ``*_TOKEN``,
``Authorization`` headers, and high-entropy ``sk-…`` / ``Bearer …`` snippets.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
import re

_REDACTED = "<redacted>"

# Each pattern must define a capture group around the value to redact; if there's
# no group we replace the whole match. Order matters: more specific patterns
# come first so we don't double-rewrite.
DEFAULT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Explicit env-style assignments: KEY=value (until whitespace, quote, or comma)
    re.compile(
        r"(?i)\b("
        r"OPENROUTER_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY|"
        r"META_APP_SECRET|META_VERIFY_TOKEN|WAPSELL_ENCRYPTION_KEY|WASELLER_ENCRYPTION_KEY|"
        r"[A-Z][A-Z0-9_]*_TOKEN|[A-Z][A-Z0-9_]*_SECRET|[A-Z][A-Z0-9_]*_PASSWORD"
        r")\s*[:=]\s*['\"]?([^\s'\",]+)"
    ),
    # Authorization headers: Bearer xxx / Basic xxx
    re.compile(r"(?i)\b(Authorization\s*:\s*(?:Bearer|Basic)\s+)([A-Za-z0-9._\-+/=]+)"),
    # Naked OpenAI-style keys
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,})"),
    # X-Hub-Signature (Meta) — not strictly secret but reveals signing oracle
    re.compile(r"(?i)(X-Hub-Signature-256\s*:\s*)(sha256=[A-Fa-f0-9]+)"),
)


def redact(text: str, patterns: Iterable[re.Pattern[str]] = DEFAULT_SECRET_PATTERNS) -> str:
    """Apply every pattern in order, replacing the *last* group of each match.

    Pure function — handy for redacting on the way out of any string sink
    (logs, error responses, traces). Idempotent: feeding a redacted string back
    in is a no-op.
    """
    out = text
    for pat in patterns:

        def _sub(m: re.Match[str], _pat: re.Pattern[str] = pat) -> str:
            if not m.groups():
                return _REDACTED
            # Rebuild the match with the *last* capture group replaced; that
            # group is the value. Earlier groups (e.g. the key name) stay so
            # the log is still useful for debugging.
            last_group_index = len(m.groups())
            start, end = m.span(last_group_index)
            return m.group(0)[: start - m.start()] + _REDACTED + m.group(0)[end - m.start() :]

        out = pat.sub(_sub, out)
    return out


class SecretRedactingFilter(logging.Filter):
    """Mutate the record in-place so downstream handlers see the redacted form.

    Attach once at the root logger; it covers stderr handlers, file handlers,
    structured JSON handlers, and any vendor shipper. Returning ``True`` lets
    the record through after rewriting.
    """

    def __init__(self, patterns: Iterable[re.Pattern[str]] = DEFAULT_SECRET_PATTERNS) -> None:
        super().__init__()
        self._patterns = tuple(patterns)

    def filter(self, record: logging.LogRecord) -> bool:
        # Format with args eagerly so a later %-format can't sneak a secret past.
        msg = record.getMessage()
        record.msg = redact(msg, self._patterns)
        record.args = ()
        return True


def install_redaction(
    logger: logging.Logger | None = None,
    patterns: Iterable[re.Pattern[str]] = DEFAULT_SECRET_PATTERNS,
) -> SecretRedactingFilter:
    """Attach the filter to ``logger`` (root by default) and return it.

    Returns the installed filter so callers can ``logger.removeFilter`` it in
    tests. Idempotent against double-install — re-running adds a second filter,
    which is a no-op (already-redacted input).
    """
    target = logger or logging.getLogger()
    flt = SecretRedactingFilter(patterns)
    target.addFilter(flt)
    return flt
