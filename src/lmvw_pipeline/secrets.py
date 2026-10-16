"""Runtime-only credentials. No defaults, command-line key flags or .env auto-loading."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .common import PipelineError


@dataclass(frozen=True)
class Secret:
    _value: str = field(repr=False)

    def reveal(self) -> str:
        """Only the HTTP transport should call this method."""
        return self._value

    def __repr__(self) -> str:
        return "Secret([REDACTED])"

    def __str__(self) -> str:
        return "[REDACTED]"


def load_secret(name: str) -> Secret:
    """Accept an injected environment variable OR a read-only mounted secret file."""
    direct = os.environ.get(name)
    filename = os.environ.get(name + "_FILE")
    if direct and filename:
        raise PipelineError(f"Set only {name} or {name}_FILE, not both")
    if filename:
        path = Path(filename)
        try:
            if path.is_symlink() or not path.is_file():
                raise PipelineError("Secret file must be a regular non-symlink file")
            if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise PipelineError("Secret file must not be accessible to group or other users")
            direct = path.read_text(encoding="utf-8").strip()
        except OSError:
            raise PipelineError("Cannot read the configured secret file") from None
    if not direct or not direct.strip():
        raise PipelineError(f"Missing runtime credential: {name}")
    value = direct.strip()
    if any(c.isspace() for c in value) or not value.isascii() or len(value) > 4096:
        raise PipelineError("Invalid credential format")
    if value.lower() in {"changeme", "replace_me", "your_api_key", "placeholder"}:
        raise PipelineError("A placeholder cannot be used as a credential")
    return Secret(value)
