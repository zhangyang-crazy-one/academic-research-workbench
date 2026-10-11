"""Versioned public harness configuration, without runtime credential values."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arw.kernel.core.canonical import canonical_json_bytes

NAME = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_FIELDS = frozenset(
    {"api_key", "authorization", "password", "access_token", "refresh_token"}
)
RESERVED_ENV = frozenset(
    {
        "HOME",
        "PATH",
        "TMPDIR",
        "PYTHONPATH",
        "PYTHONHOME",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "CODEX_HOME",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    }
)


class HarnessConfigError(ValueError):
    """Invalid selector or unavailable runtime input; values are never echoed."""


class HarnessEntry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    kind: Annotated[str, Field(pattern=NAME)]
    command: tuple[str, ...] = ()
    runtime_roots: tuple[str, ...] = ()
    credential_env: tuple[str, ...] = ()
    env_file: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    endpoint: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    model: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    protocol: Literal["responses", "chat_completions"] = "responses"
    api_key_env: str | None = None
    max_output_tokens: Annotated[int, Field(ge=16, le=32768)] = 4096
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"] | None = None
    allow_http: bool = False
    parameters: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_runtime_contract(self):
        names = (
            *self.credential_env,
            *((self.api_key_env,) if self.api_key_env else ()),
        )
        if any(not ENV_NAME.fullmatch(name) for name in names):
            raise ValueError("credential selectors must be environment variable names")
        if RESERVED_ENV.intersection(names):
            raise ValueError("credential selector cannot replace task runtime controls")
        if len(set(self.credential_env)) != len(self.credential_env):
            raise ValueError("duplicate credential environment selector")
        if any(
            not value or "\x00" in value
            for value in (*self.command, *self.runtime_roots)
        ):
            raise ValueError("empty or NUL command/runtime value")
        if self.kind == "command" and not self.command:
            raise ValueError("command harness requires an argv array")
        if self.kind == "command" and (self.endpoint or self.model or self.api_key_env):
            raise ValueError("command harness cannot select API transport options")
        if self.kind == "api":
            if not self.endpoint or not self.model or not self.model.strip():
                raise ValueError("API harness requires an endpoint and explicit model")
            address = urlsplit(self.endpoint)
            if (
                address.scheme not in {"https", "http"}
                or not address.hostname
                or address.username is not None
                or address.password is not None
                or address.fragment
                or address.query
            ):
                raise ValueError("API endpoint must be a credential-free HTTP(S) URL")
            local = address.hostname in {"localhost", "127.0.0.1", "::1"}
            if address.scheme == "http" and not (local or self.allow_http):
                raise ValueError("non-loopback HTTP requires explicit allow_http")
            if self.command or self.runtime_roots or self.credential_env:
                raise ValueError("API harness cannot select an external executable")
            forbidden = {
                "model",
                "messages",
                "input",
                "instructions",
                "tools",
                "tool_choice",
                "functions",
                "function_call",
                "background",
                "prompt",
                "web_search_options",
                "conversation",
                "previous_response_id",
                "thread_id",
                "store",
                "stream",
                "n",
                "max_tokens",
                "max_completion_tokens",
                "max_output_tokens",
            }
            if forbidden.intersection(self.parameters):
                raise ValueError(
                    "API parameters cannot replace context, tools or execution bounds"
                )
        if self.kind == "codex" and (
            self.command
            or self.runtime_roots
            or self.endpoint
            or self.model
            or self.api_key_env
            or self.credential_env
            or self.env_file
            or self.parameters
            or self.reasoning_effort
            or self.allow_http
            or self.max_output_tokens != 4096
            or self.protocol != "responses"
        ):
            raise ValueError(
                "Codex uses its existing qualified native host configuration"
            )

        def public(value):
            if isinstance(value, dict):
                if SECRET_FIELDS.intersection(str(key).lower() for key in value):
                    raise ValueError(
                        "literal credentials are not accepted in harness parameters"
                    )
                for child in value.values():
                    public(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    public(child)

        public(self.parameters)
        canonical_json_bytes(self.model_dump(mode="json"))
        return self


class HarnessConfiguration(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["arw.harness-config.v1"]
    default: Annotated[str, Field(pattern=NAME)]
    harnesses: Annotated[dict[str, HarnessEntry], Field(min_length=1, max_length=64)]
    assignments: dict[str, str] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def selectors_exist(self):
        if any(not re.fullmatch(NAME, name) for name in self.harnesses):
            raise ValueError("invalid harness name")
        if any(
            name not in self.harnesses
            for name in (self.default, *self.assignments.values(), *self.roles.values())
        ):
            raise ValueError("harness selector is not configured")
        if any(
            not re.fullmatch(NAME, name) for name in (*self.assignments, *self.roles)
        ):
            raise ValueError("invalid assignment or role selector")
        return self

    @property
    def config_sha256(self) -> str:
        return hashlib.sha256(
            canonical_json_bytes(self.model_dump(mode="json"))
        ).hexdigest()

    def select(self, assignment_id: str, role_id: str) -> tuple[str, HarnessEntry]:
        name = self.assignments.get(
            assignment_id, self.roles.get(role_id, self.default)
        )
        return name, self.harnesses[name]
