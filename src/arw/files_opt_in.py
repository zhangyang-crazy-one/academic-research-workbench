"""Explicit, project-scoped activation of the optional native file-base MCP."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from pathlib import Path

SCHEMA_VERSION = "arw.files-opt-in.v1"
ROOT_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


class OptInError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def plugin_root() -> Path:
    configured = os.environ.get("ARW_PLUGIN_ROOT")
    if configured:
        base = Path(configured)
        if not base.is_absolute() or any(
            part.is_symlink() for part in (base, *base.parents)
        ):
            raise OptInError(
                "plugin_root_invalid",
                "plugin root must be an absolute non-symlink directory",
            )
        if not base.is_dir() or not (base / ".mcp.json").is_file():
            raise OptInError("plugin_root_invalid", "plugin root is unavailable")
        return base.resolve(strict=True)
    source = Path(__file__).resolve().parents[2]
    if (source / "src/arw/files_opt_in.py").is_file():
        return source
    raise OptInError(
        "plugin_root_unbound", "the installed launcher must bind ARW_PLUGIN_ROOT"
    )


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and os.access(path, os.X_OK)
    except OSError:
        return False


def _project_config_state(path: Path, host: str) -> str:
    if not path.exists():
        return "absent"
    if path.is_symlink() or not path.is_file():
        return "invalid"
    try:
        raw = path.read_bytes()
        if len(raw) > 1_048_576:
            return "invalid"
        data = (
            json.loads(raw) if host == "claude" else tomllib.loads(raw.decode("utf-8"))
        )
        servers = data.get("mcpServers" if host == "claude" else "mcp_servers", {})
        if not isinstance(servers, dict):
            return "invalid"
        entry = servers.get("file-base")
        if entry is None:
            return "absent"
        required = {"CBM_ALLOWED_ROOT", "CBM_ALLOWED_ROOT_ID", "CBM_CACHE_DIR"}
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
            return "invalid"
        env = entry.get("env")
        return (
            "configured"
            if isinstance(env, dict) and required.issubset(env)
            else "invalid"
        )
    except (OSError, ValueError, UnicodeError, AttributeError):
        return "invalid"


def health(root: Path | None = None) -> dict[str, object]:
    try:
        base = root or plugin_root()
    except OptInError as error:
        return {
            "state": "unavailable",
            "reason_code": error.code,
            "bundle_state": "unknown",
            "native_binary": "unknown",
            "project_configs": {"codex": "not_checked", "claude": "not_checked"},
            "enable_command": "run the installed bin/arw launcher to inspect file-base",
        }
    try:
        payload = json.loads((base / ".mcp.json").read_text(encoding="utf-8"))
        servers = payload.get("mcpServers")
        configured = isinstance(servers, dict) and "file-base" in servers
    except (OSError, ValueError, AttributeError):
        configured = False
    native_ready = _regular_file(base / "libexec/file-base-mcp")
    project_configs = {
        "codex": _project_config_state(Path.cwd() / ".codex/config.toml", "codex"),
        "claude": _project_config_state(Path.cwd() / ".mcp.json", "claude"),
    }
    project_enabled = "configured" in project_configs.values()
    if configured:
        state, reason_code = "bundled", "bundled_registration"
    elif project_enabled and native_ready:
        state, reason_code = "enabled", "project_configured"
    elif project_enabled:
        state, reason_code = "unavailable", "native_binary_missing"
    else:
        state, reason_code = "disabled", "opt_in_required"
    return {
        "state": state,
        "reason_code": reason_code,
        "bundle_state": "registered" if configured else "disabled",
        "native_binary": "ready" if native_ready else "missing",
        "project_configs": project_configs,
        "enable_command": "arw files enable --provider native --host codex|claude --target PATH --root PATH --root-id ID --cache-dir PATH",
    }


def _safe_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise OptInError(f"{label}_not_absolute", f"{label} must be absolute")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise OptInError(f"{label}_symlink", f"{label} must not contain symlinks")
    if not path.is_dir():
        raise OptInError(f"{label}_missing", f"{label} must be an existing directory")
    return path.resolve(strict=True)


def _target(path: Path, host: str) -> Path:
    if not path.is_absolute():
        raise OptInError("target_not_absolute", "target must be absolute")
    expected = (".codex", "config.toml") if host == "codex" else ("", ".mcp.json")
    if path.name != expected[1] or (
        host == "codex" and path.parent.name != expected[0]
    ):
        raise OptInError(
            "invalid_project_target",
            "target must be the selected host's project config file",
        )
    project = _safe_directory(
        path.parent.parent if host == "codex" else path.parent, "project"
    )
    parent = _safe_directory(path.parent, "target_parent")
    canonical_target = parent / path.name
    home = Path.home().resolve()
    if project in {Path("/"), home}:
        raise OptInError("global_target_denied", "target must belong to a project")
    protected = [home / ".codex", home / ".claude"]
    for name in ("CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        value = os.environ.get(name)
        if value:
            protected.append(Path(value).resolve())
    if any(canonical_target.is_relative_to(directory) for directory in protected):
        raise OptInError(
            "global_target_denied", "target must not be a host configuration directory"
        )
    if path.is_symlink():
        raise OptInError("target_symlink", "target must not be a symlink")
    if canonical_target.exists() and not canonical_target.is_file():
        raise OptInError("target_not_file", "target must be a regular file")
    return canonical_target


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _render_config(
    host: str, existing: bytes, command: Path, env: dict[str, str]
) -> bytes:
    if host == "claude":
        try:
            data = json.loads(existing) if existing else {}
        except (ValueError, UnicodeError) as error:
            raise OptInError(
                "invalid_target_config", "target JSON is invalid"
            ) from error
        if not isinstance(data, dict) or not isinstance(
            data.get("mcpServers", {}), dict
        ):
            raise OptInError(
                "invalid_target_config", "target MCP configuration is invalid"
            )
        servers = data.setdefault("mcpServers", {})
        if "file-base" in servers:
            raise OptInError(
                "server_already_configured", "file-base is already configured"
            )
        servers["file-base"] = {"command": str(command), "env": env}
        return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        data = tomllib.loads(existing.decode("utf-8")) if existing else {}
    except (ValueError, UnicodeError) as error:
        raise OptInError("invalid_target_config", "target TOML is invalid") from error
    if not isinstance(data.get("mcp_servers", {}), dict):
        raise OptInError("invalid_target_config", "target MCP configuration is invalid")
    if "file-base" in data.get("mcp_servers", {}):
        raise OptInError("server_already_configured", "file-base is already configured")
    lines = [
        '[mcp_servers."file-base"]',
        f"command = {_toml_string(str(command))}",
        "",
        '[mcp_servers."file-base".env]',
    ]
    lines.extend(f"{key} = {_toml_string(value)}" for key, value in env.items())
    return (
        existing.rstrip(b"\n")
        + ("\n\n" if existing else "").encode()
        + ("\n".join(lines) + "\n").encode()
    )


def enable(
    *, provider: str, host: str, target: Path, root: Path, root_id: str, cache_dir: Path
) -> dict[str, object]:
    if sys.version_info < (3, 13):  # noqa: UP036 - explicit provider preflight
        raise OptInError("runtime_unsupported", "Python 3.13 or newer is required")
    if provider != "native":
        raise OptInError(
            "provider_unsupported", "only the native file-base provider is supported"
        )
    if host not in {"codex", "claude"}:
        raise OptInError("host_unsupported", "host must be codex or claude")
    if not ROOT_ID.fullmatch(root_id):
        raise OptInError("invalid_root_id", "root ID is invalid")
    root = _safe_directory(root, "root")
    if root in {Path("/"), Path.home().resolve()}:
        raise OptInError("unsafe_root", "root cannot be filesystem root or home")
    cache_dir = _safe_directory(cache_dir, "cache")
    if cache_dir == root or cache_dir.is_relative_to(root):
        raise OptInError("cache_inside_root", "cache must be outside the research root")
    target = _target(target, host)
    base = plugin_root()
    if target == base / ".mcp.json" or (
        (base / "share/arw/wheels").is_dir() and target.is_relative_to(base)
    ):
        raise OptInError(
            "bundled_config_target_denied",
            "target must be a project config outside the plugin bundle",
        )
    command = base / "scripts/file-base-mcp"
    native = base / "libexec/file-base-mcp"
    if not _regular_file(command):
        raise OptInError(
            "provider_launcher_missing", "installed file-base launcher is unavailable"
        )
    if not _regular_file(native):
        raise OptInError(
            "native_binary_missing",
            "native file-base binary is unavailable; build or install a qualified stage",
        )
    env = {
        "CBM_ALLOWED_ROOT": str(root),
        "CBM_ALLOWED_ROOT_ID": root_id,
        "CBM_CACHE_DIR": str(cache_dir),
        "CBM_DISABLE_UPDATE_CHECK": "1",
        "CBM_LOG_LEVEL": "warn",
    }
    try:
        existed = target.exists()
        existing = target.read_bytes() if existed else b""
        rendered = _render_config(host, existing, command, env)
        mode = stat.S_IMODE(target.stat().st_mode) if existed else 0o600
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=".arw-mcp-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            try:
                if stream.write(rendered) != len(rendered):
                    raise OSError("short configuration write")
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.chmod(mode)
            if existed:
                # Preserve unknown settings and avoid replacing a changed file.
                if not target.is_file() or target.read_bytes() != existing:
                    raise OptInError(
                        "target_changed", "target changed during preflight"
                    )
                os.replace(temporary, target)
            else:
                # Same-directory hard link publishes complete bytes atomically and
                # refuses to overwrite a target created during preflight.
                try:
                    os.link(temporary, target)
                except FileExistsError as error:
                    raise OptInError(
                        "target_changed", "target appeared during preflight"
                    ) from error
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as error:
        raise OptInError(
            "target_write_failed", "cannot write the project target"
        ) from error
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "enabled",
        "host": host,
        "provider": provider,
        "target": str(target),
    }


def diagnostic(error: OptInError) -> dict[str, str]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "rejected",
        "reason_code": error.code,
        "message": str(error),
    }


def source_main(argv: list[str] | None = None) -> int:
    """Stdlib-only source-checkout path, before an installed wheel exists."""
    parser = argparse.ArgumentParser(prog="arw files enable")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--root-id", required=True)
    parser.add_argument("--cache-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = enable(
            provider=args.provider,
            host=args.host,
            target=args.target,
            root=args.root,
            root_id=args.root_id,
            cache_dir=args.cache_dir,
        )
    except OptInError as error:
        result = diagnostic(error)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "enabled" else 65


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1:] == ["health", "--json"]:
        from arw.platform_support import platform_support

        print(
            json.dumps(
                {
                    "command": "health",
                    "status": "ok",
                    "file_base": health(),
                    "platform": platform_support(),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "enable":
        raise SystemExit(source_main(sys.argv[2:]))
    print(
        json.dumps(
            diagnostic(
                OptInError(
                    "invalid_command", "expected health --json or enable options"
                )
            )
        )
    )
    raise SystemExit(64)
