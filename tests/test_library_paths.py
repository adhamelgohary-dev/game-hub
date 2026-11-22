import os
from pathlib import Path

import pytest

from gamehub.core.library.paths import contained_file, local_path


@pytest.mark.parametrize("relative", [r"..\g.exe", r"C:g.exe", r"\g.exe", r"g.exe:ads", "NUL.exe", ".\\g.exe"])
def test_containment_rejects_nonplain_relative_paths(tmp_path: Path, relative: str) -> None:
    (tmp_path / "g.exe").touch()

    assert contained_file(tmp_path, relative) is None


def test_containment_accepts_existing_nested_file(tmp_path: Path) -> None:
    directory = tmp_path / "Bin"
    directory.mkdir()
    executable = directory / "g.exe"
    executable.touch()

    assert contained_file(tmp_path, r"Bin\g.exe") == executable
    assert contained_file(tmp_path, "Bin") is None


def test_unc_rejected_before_filesystem_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def probe(*_args):
        pytest.fail("Unexpected filesystem probe of a network path")

    monkeypatch.setattr(Path, "lstat", probe)

    assert local_path(r"\\network\share\g.exe") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows mapped drives use Win32 GetDriveTypeW")
def test_mapped_network_drive_rejected_before_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctypes

    def probe(*_args):
        pytest.fail("Unexpected filesystem probe of a mapped network drive")

    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda _drive: 4)
    monkeypatch.setattr(Path, "lstat", probe)

    assert local_path(r"Z:\g.exe") is None
