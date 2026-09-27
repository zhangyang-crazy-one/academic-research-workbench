"""Conservative, observational platform support reported by health."""

from __future__ import annotations

import platform


def platform_support(system: str | None = None) -> dict[str, object]:
    name = (system or platform.system()).lower()
    if name == "linux":
        return {
            "system": "Linux",
            "tier": "tier-1",
            "supported": True,
            "unavailable_capabilities": [],
        }
    if name == "darwin":
        return {
            "system": "macOS",
            "tier": "tier-2",
            "supported": True,
            "unavailable_capabilities": ["network-denied-native-build"],
        }
    return {
        "system": platform.system() if system is None else system,
        "tier": "unsupported",
        "supported": False,
        "unavailable_capabilities": [
            "native-file-base",
            "descriptor-relative-file-access",
            "network-denied-native-build",
            "bash-launcher",
        ],
    }
