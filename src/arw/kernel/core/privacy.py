"""Reject common secret shapes before durable output; not a completeness proof."""

import re

_PATTERNS = (
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b",
    r'(?i)\b(?:password|api[_-]?key|access[_-]?token|authorization)\s*[=:]\s*["\']?[^\s"\',}]{8,}',
    r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}",
    r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb)://[^\s/:]+:[^\s/@]+@",
)


class SecretRejected(ValueError):
    code = "secret_rejected"

    def __init__(self):
        super().__init__("secret-shaped input rejected before durable storage")


def reject_secret_shapes(raw: bytes | str) -> None:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    if any(re.search(pattern, text) for pattern in _PATTERNS):
        raise SecretRejected()
