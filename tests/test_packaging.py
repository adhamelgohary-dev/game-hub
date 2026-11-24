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
FORBIDDEN_RUNTIME_MODULES = {
    "cv2",
    "psutil",
}
FORBIDDEN_DYNAMIC_BUILTINS = {
    "__import__",
    "compile",
    "eval",
    "exec",
}
ALLOWED_CTYPES_DLLS = {
    "advapi32",
    "combase",
    "crypt32",
    "dwmapi",
    "kernel32",
    "ole32",
    "shell32",
    "user32",
}
FORBIDDEN_NATIVE_SYMBOLS = (
    "AdjustTokenPrivileges",
    "CreateRemoteThread",
    "CreateService",
    "EnumProcessModules",
    "GetModuleFileNameEx",
    "GetProcAddress",
    "K32EnumProcessModules",
    "LoadLibraryA",
    "LoadLibraryExA",
    "LoadLibraryExW",
    "LoadLibraryW",
    "NtOpenProcess",
    "NtQuerySystemInformation",
    "NtReadVirtualMemory",
    "NtWriteVirtualMemory",
    "OpenProcessToken",
    "PROCESS_ALL_ACCESS",
    "PROCESS_VM_READ",
    "PROCESS_VM_WRITE",
    "QNetworkAccessManager",
    "QSystemTrayIcon",
    "QTcpSocket",
    "QUdpSocket",
    "QWebEngineView",
    "QueueUserAPC",
    "ReadProcessMemory",
    "SeDebugPrivilege",
    "SendInput",
    "SetThreadContext",
    "SetValueEx",
    "SetWinEventHook",
    "SetWindowsHookEx",
    "StartService",
    "VirtualAllocEx",
    "VirtualProtectEx",
    "WriteProcessMemory",
    "ZwOpenProcess",
    "keybd_event",
    "mouse_event",
)


OPT_IN_NETWORK_ALLOWED = {
    "gamehub/core/library/steamgriddb.py": {"urllib"},
}


def test_app_makes_no_network_imports_and_no_game_injection_calls() -> None:
    for path in sorted(Path("gamehub").rglob("*.py")):
        rel = path.as_posix()
        allowed_net = OPT_IN_NETWORK_ALLOWED.get(rel, set())
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in FORBIDDEN_RUNTIME_MODULES, (
                        f"Forbidden runtime module {alias.name!r} in {path}"
                    )
                    assert root not in FORBIDDEN_NETWORK_MODULES or root in allowed_net, (
                        f"Forbidden network import {alias.name!r} in {path}"
                    )
                    if alias.name == "PySide6.QtNetwork" and rel != "gamehub/single_instance.py":
                        raise AssertionError(f"PySide6.QtNetwork restricted to single_instance.py: {path}")
                    if alias.name == "PySide6.QtMultimedia" and rel != "gamehub/core/audio/player.py":
                        raise AssertionError(f"PySide6.QtMultimedia restricted to audio/player.py: {path}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in FORBIDDEN_RUNTIME_MODULES, (
                    f"Forbidden runtime module {node.module!r} in {path}"
                )
                assert root not in FORBIDDEN_NETWORK_MODULES or root in allowed_net, (
                    f"Forbidden network import {node.module!r} in {path}"
                )
                if node.module == "PySide6.QtNetwork" and rel != "gamehub/single_instance.py":
                    raise AssertionError(f"PySide6.QtNetwork restricted to single_instance.py: {path}")
                if node.module == "PySide6.QtMultimedia" and rel != "gamehub/core/audio/player.py":
                    raise AssertionError(f"PySide6.QtMultimedia restricted to audio/player.py: {path}")
                if node.module == "PySide6":
                    for alias in node.names:
                        if alias.name == "QtNetwork" and rel != "gamehub/single_instance.py":
                            raise AssertionError(f"PySide6.QtNetwork restricted to single_instance.py: {path}")
                        if alias.name == "QtMultimedia" and rel != "gamehub/core/audio/player.py":
                            raise AssertionError(f"PySide6.QtMultimedia restricted to audio/player.py: {path}")
                if node.module == "importlib":
                    for alias in node.names:
                        if alias.name == "import_module":
                            raise AssertionError(f"Dynamic importlib.import_module forbidden in {path}")
            elif isinstance(node, ast.Subscript):
                # Restrict sys.modules mutations strictly to the cv2 shim in capture/windows.py.
                if (
                    isinstance(node.ctx, (ast.Store, ast.Del))
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "modules"
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "sys"
                    and rel != "gamehub/core/capture/windows.py"
                ):
                    raise AssertionError(f"sys.modules mutation forbidden outside capture/windows.py: {path}")
                # Block ctypes.windll["..."] / cdll["..."] / oledll["..."] / pydll["..."]
                if (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr in {"windll", "cdll", "oledll", "pydll"}
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "ctypes"
                ):
                    raise AssertionError(f"Dynamic ctypes.{node.value.attr}[...] forbidden in {path}")
            elif isinstance(node, ast.Attribute):
                # Enforce allowlist on ctypes.<loader>.<dll> attribute access
                if (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr in {"windll", "cdll", "oledll", "pydll"}
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "ctypes"
                ):
                    dll_name = node.attr.lower().removesuffix(".dll")
                    assert dll_name in ALLOWED_CTYPES_DLLS, (
                        f"Non-allowlisted ctypes.{node.value.attr}.{node.attr} in {path}"
                    )
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_DYNAMIC_BUILTINS:
                    raise AssertionError(f"Forbidden dynamic builtin {node.func.id!r} in {path}")
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in FORBIDDEN_DYNAMIC_BUILTINS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "builtins"
                ):
                    raise AssertionError(f"Forbidden builtins.{node.func.attr} in {path}")
                func_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
                )
                if func_name == "import_module":
                    raise AssertionError(f"Dynamic import_module forbidden in {path}")
                if func_name in {"WinDLL", "CDLL", "OleDLL", "PyDLL", "LibraryLoader", "LoadLibrary"}:
                    name_node = node.args[0] if node.args else next(
                        (kw.value for kw in node.keywords if kw.arg == "name"), None
                    )
                    if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
                        raise AssertionError(f"Dynamic ctypes DLL load is forbidden in {path}")
                    dll_name = name_node.value.lower().removesuffix(".dll")
                    assert dll_name in ALLOWED_CTYPES_DLLS, (
                        f"Non-allowlisted DLL {name_node.value!r} loaded in {path}"
                    )
                    if dll_name == "crypt32" and rel != "gamehub/core/secrets.py":
                        raise AssertionError(f"crypt32 restricted to gamehub/core/secrets.py: {path}")

        for symbol in FORBIDDEN_NATIVE_SYMBOLS:
            assert symbol not in source, f"Forbidden Win32 API {symbol!r} in {path}"
        if rel != "gamehub/core/sessions/processes.py":
            assert "OpenProcess" not in source, f"Forbidden OpenProcess outside processes.py in {path}"
        if rel != "gamehub/core/protection/guard.py":
            assert "K32EnumProcesses" not in source, f"K32EnumProcesses restricted to guard.py: {path}"

    # Verify EVERY self._open(...) call in processes.py uses strictly _QUERY_LIMITED_INFORMATION (0x1000).
    proc_path = Path("gamehub/core/sessions/processes.py")
    proc_src = proc_path.read_text(encoding="utf-8")
    proc_tree = ast.parse(proc_src)
    open_calls = [
        node
        for node in ast.walk(proc_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_open"
    ]
    assert open_calls, "Expected at least one self._open call in processes.py"
    for call in open_calls:
        assert call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == "_QUERY_LIMITED_INFORMATION"
    assert "_QUERY_LIMITED_INFORMATION = 0x1000" in proc_src
    assert "psutil" not in proc_src

    xbox_src = Path("gamehub/core/library/xbox.py").read_text(encoding="utf-8")
    assert "powershell" not in xbox_src.lower()
    assert "subprocess" not in xbox_src

    sgdb_src = Path("gamehub/core/library/steamgriddb.py").read_text(encoding="utf-8")
    assert "https://www.steamgriddb.com/api/v2" in sgdb_src
    assert "if not enabled or not key or not query:" in sgdb_src
    assert "_NoRedirectHandler" in sgdb_src
    assert "_ALLOWED_CDN_HOSTS" in sgdb_src

    manifest = Path("packaging/GameRewind.manifest").read_text(encoding="utf-8")
    assert "asInvoker" in manifest
    assert "requireAdministrator" not in manifest
    assert "highestAvailable" not in manifest

    spec_src = Path("packaging/gamerewind.spec").read_text(encoding="utf-8")
    spec_tree = ast.parse(spec_src)
    for target_ctor in ("EXE", "COLLECT"):
        ctor_calls = [
            node
            for node in ast.walk(spec_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == target_ctor
        ]
        assert ctor_calls, f"Missing {target_ctor}(...) in gamerewind.spec"
        for call in ctor_calls:
            upx_kw = next((kw for kw in call.keywords if kw.arg == "upx"), None)
            assert (
                upx_kw is not None
                and isinstance(upx_kw.value, ast.Constant)
                and upx_kw.value.value is False
            ), f"{target_ctor} must explicitly set upx=False in gamerewind.spec"
    assert "'psutil'" in spec_src
    assert "'cv2'" in spec_src
    assert "'opengl32sw'" in spec_src


def test_packaging_definitions_and_third_party_licenses_are_complete() -> None:
    root = Path(".")
    spec_text = (root / "packaging" / "gamerewind.spec").read_text(encoding="utf-8")
    installer_text = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    notices_text = (root / "packaging" / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")

    for license_file in ("GPL-3.0.txt", "LGPL-3.0.txt", "LGPL-2.1.txt", "PortAudio.txt"):
        path = root / "packaging" / "licenses" / license_file
        assert path.is_file() and path.stat().st_size > 100, f"Missing license {path}"
        assert license_file in spec_text

    # Every pinned runtime dependency must be collected for notices in gamerewind.spec.
    for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        package = stripped.split("==")[0]
        assert package.lower() != "psutil", "psutil must not be bundled in GameRewind"
        assert not package.lower().startswith("opencv-"), "OpenCV must not be bundled in GameRewind"
        assert f"'{package}'" in spec_text, f"Missing {package!r} in packaging/gamerewind.spec"

    assert __version__
    assert "PrivilegesRequired=lowest" in installer_text
    assert "DisableDirPage=no" in installer_text
    assert "UsePreviousAppDir=no" in installer_text
    assert "DefaultDirName={localappdata}\\Programs\\GameRewind" in installer_text
    assert "GameRewind-Setup" in installer_text
    assert 'Name: "desktopicon"' in installer_text
    assert "IsDirWritable" in installer_text
    assert "IsForbiddenDestination" in installer_text
    assert "ValidateInstallDir" in installer_text
    assert "RunValidatedQuietUninstaller" in installer_text
    assert "LegacyGameHubUninstallKey" in installer_text
    assert "Flags: deletevalue uninsdeletevalue dontcreatekey" in installer_text
    assert "ValueType: none" in installer_text
    assert "[InstallDelete]" in installer_text
    assert "protected_games.json" in spec_text
    assert "version_info.txt" in spec_text
    assert "GameRewind.manifest" in spec_text
    assert "FFmpeg" in notices_text
    assert "PySide6 Addons" in notices_text
    assert "MIT License" in notices_text
    assert "Game Hub" not in notices_text
    assert (root / "LICENSE").is_file()
    assert "MIT License" in (root / "LICENSE").read_text(encoding="utf-8")
    assert (root / "SECURITY.md").is_file()
    assert (root / "CONTRIBUTING.md").is_file()
    assert (root / "docs" / "SIGNPATH-APPLICATION.md").is_file()
    assert (root / "packaging" / "version_info.txt").is_file()
    assert (root / "packaging" / "GameRewind.manifest").is_file()
    for asset in ("GameRewind.ico", "GameRewind.png", "wizard-sidebar.bmp", "wizard-header.bmp"):
        assert (root / "packaging" / "assets" / asset).is_file(), f"Missing asset {asset}"
    assert "GameRewind.ico" in spec_text and "GameRewind.png" in spec_text
    assert "SetupIconFile=assets\\GameRewind.ico" in installer_text
    assert "WizardImageFile=assets\\wizard-sidebar.bmp" in installer_text
    assert "WizardSmallImageFile=assets\\wizard-header.bmp" in installer_text
    assert (root / "docs" / "USER-GUIDE-AR.md").is_file()
    workflow_text = (root / ".github" / "workflows" / "windows.yml").read_text(encoding="utf-8")
    assert "SIGNPATH_ENABLED" in workflow_text
    assert "SHA256SUMS.txt" in workflow_text
    assert "tags: ['v*']" in workflow_text
    assert "GameRewind-Setup-" in workflow_text
    assert "GameRewind-Portable-" in workflow_text
    assert "MpCmdRun.exe" in workflow_text
    assert "highestAvailable" in workflow_text
    assert "Verify bundle size and excluded binaries gate" in workflow_text
    assert "@v4" not in workflow_text and "@v3" not in workflow_text


def test_cv2_shim_allows_windows_capture_without_opencv() -> None:
    import sys

    import pytest

    from gamehub.core.capture.windows import ensure_cv2_shim

    ensure_cv2_shim()
    assert "cv2" in sys.modules
    import cv2

    with pytest.raises(RuntimeError, match="not bundled"):
        _ = cv2.imwrite
    from inspect import signature

    from windows_capture import WindowsCapture

    assert "window_hwnd" in signature(WindowsCapture).parameters
