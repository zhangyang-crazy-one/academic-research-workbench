from arw.platform_support import platform_support


def test_platform_support_reports_capability_limits() -> None:
    assert platform_support("Linux")["tier"] == "tier-1"
    macos = platform_support("Darwin")
    assert macos["tier"] == "tier-2"
    assert "network-denied-native-build" in macos["unavailable_capabilities"]
    windows = platform_support("Windows")
    assert windows["supported"] is False
    assert "descriptor-relative-file-access" in windows["unavailable_capabilities"]
