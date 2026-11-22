import ast
from pathlib import Path

from gamehub import __version__

FORBIDDEN_NETWORK_MODULES = {
    "aiohttp",
    "ftplib",
    "http",
    "httpx",
    "requests",
    "smtplib",
    "socket",
    "urllib",
    "urllib3",
    "websockets",
}
FORBIDDEN_NATIVE_SYMBOLS = (
    "CreateRemoteThread",
    "NtReadVirtualMemory",
    "NtWriteVirtualMemory",
    "PROCESS_ALL_ACCESS",
    "PROCESS_VM_READ",
    "PROCESS_VM_WRITE",
    "QNetworkAccessManager",
    "QSystemTrayIcon",
    "QTcpSocket",
    "QUdpSocket",
    "ReadProcessMemory",
    "SeDebugPrivilege",
    "SetValueEx",
    "SetWindowsHookEx",
    "VirtualAllocEx",
    "WriteProcessMemory",
)


def test_app_makes_no_network_imports_and_no_game_injection_calls() -> None:
    for path in sorted(Path("gamehub").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in FORBIDDEN_NETWORK_MODULES, (
                        f"Forbidden network import {alias.name!r} in {path}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in FORBIDDEN_NETWORK_MODULES, (
                    f"Forbidden network import {node.module!r} in {path}"
                )
        for symbol in FORBIDDEN_NATIVE_SYMBOLS:
            assert symbol not in source, f"Forbidden Win32 API {symbol!r} in {path}"


def test_packaging_definitions_and_third_party_licenses_are_complete() -> None:
    root = Path(".")
    spec_text = (root / "packaging" / "gamehub.spec").read_text(encoding="utf-8")
    installer_text = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    notices_text = (root / "packaging" / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")

    for license_file in ("GPL-3.0.txt", "LGPL-3.0.txt", "LGPL-2.1.txt", "PortAudio.txt"):
        path = root / "packaging" / "licenses" / license_file
        assert path.is_file() and path.stat().st_size > 100, f"Missing license {path}"
        assert license_file in spec_text

    # Every pinned runtime dependency must be collected for notices in gamehub.spec.
    for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        package = stripped.split("==")[0]
        assert f"'{package}'" in spec_text, f"Missing {package!r} in packaging/gamehub.spec"

    assert __version__ == "1.0.0"
    assert "PrivilegesRequired=lowest" in installer_text
    assert "GameHub-Setup" in installer_text
    assert "Flags: deletevalue uninsdeletevalue dontcreatekey" in installer_text
    assert "ValueType: none" in installer_text
    assert "[InstallDelete]" in installer_text
    assert "protected_games.json" in spec_text
    assert "version_info.txt" in spec_text
    assert "GameHub.manifest" in spec_text
    assert "FFmpeg" in notices_text
    assert "PySide6 Addons" in notices_text
    assert "MIT License" in notices_text
    assert (root / "LICENSE").is_file()
    assert "MIT License" in (root / "LICENSE").read_text(encoding="utf-8")
    assert (root / "SECURITY.md").is_file()
    assert (root / "CONTRIBUTING.md").is_file()
    assert (root / "docs" / "SIGNPATH-APPLICATION.md").is_file()
    assert (root / "packaging" / "version_info.txt").is_file()
    assert (root / "packaging" / "GameHub.manifest").is_file()
    assert (root / "docs" / "USER-GUIDE-AR.md").is_file()
    workflow_text = (root / ".github" / "workflows" / "windows.yml").read_text(encoding="utf-8")
    assert "SIGNPATH_ENABLED" in workflow_text
    assert "SHA256SUMS.txt" in workflow_text
    assert "tags: ['v*']" in workflow_text
