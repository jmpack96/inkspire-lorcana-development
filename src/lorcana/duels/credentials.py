"""Credential references for Duels connections.

The initial platform deliberately stores only secret references in PostgreSQL.
This supports Railway environment variables without ever persisting bearer
credentials in application tables or logs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping


class DuelsCredentialError(RuntimeError):
    pass


class EnvironmentCredentialResolver:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env

    def resolve(self, credential_ref: str) -> str:
        prefix = "env:"
        if not credential_ref.startswith(prefix):
            raise DuelsCredentialError("Only env: credential references are supported")
        name = credential_ref[len(prefix):].strip()
        if not name:
            raise DuelsCredentialError("Duels credential environment variable name is empty")
        token = self.env.get(name)
        if token is None or not token.strip():
            raise DuelsCredentialError(f"Duels credential environment variable {name} is not configured")
        return token.strip()
