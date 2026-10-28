"""Small shared text boundary for material entering business state or model context.

The filter deliberately returns only redacted text and replacement counts. Callers must
never log rejected input or include raw matched values in errors.
"""

import re
from dataclasses import dataclass

MAX_SNAPSHOT_CHARS = 200_000
MAX_OPINION_CHARS = 4_000

PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)
ASSIGNMENT = re.compile(
    r"(?im)\b(api[_-]?key|secret|password|passwd|access[_-]?token|client[_-]?secret)\b"
    r"([ \t]*[:=][ \t]*)(['\"]?)([^\s'\"`]{8,})(['\"]?)"
)
BEARER = re.compile(r"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/-]{16,}")
OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


class ContentRejected(ValueError):
    pass


@dataclass(frozen=True)
class SafetyResult:
    text: str
    replacements: int

    @property
    def changed(self) -> bool:
        return self.replacements > 0


def filter_text(raw: str, *, max_chars: int = MAX_SNAPSHOT_CHARS) -> SafetyResult:
    if not raw or not raw.strip():
        raise ContentRejected("empty_text")
    if len(raw) > max_chars:
        raise ContentRejected("too_long")
    if "\x00" in raw or any(ord(char) < 32 and char not in "\n\r\t" for char in raw):
        raise ContentRejected("invalid_control_character")
    text, count = PRIVATE_KEY.subn(
        lambda match: "[已移除私钥]" + "\n" * match.group(0).count("\n"), raw
    )
    text, n = ASSIGNMENT.subn(lambda match: f"{match.group(1)}{match.group(2)}[已脱敏]", text)
    count += n
    text, n = BEARER.subn("Bearer [已脱敏]", text)
    count += n
    text, n = OPENAI_KEY.subn("[已脱敏密钥]", text)
    count += n
    text, n = AWS_KEY.subn("[已脱敏密钥]", text)
    count += n
    return SafetyResult(text=text, replacements=count)
