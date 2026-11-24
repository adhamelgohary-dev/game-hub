"""Generate clean sample translation and mod .zip packs for tests and owner verification."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path


def _write_pack_zip(
    output_path: Path,
    *,
    pkg_id: str,
    name: str,
    name_ar: str,
    kind: str,
    version: str,
    author: str,
    description: str,
    description_ar: str,
    file_contents: Mapping[str, bytes],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    for rel_path, content in file_contents.items():
        manifest_files.append(
            {
                "src": rel_path,
                "dest": rel_path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "id": pkg_id,
        "name": name,
        "name_ar": name_ar,
        "kind": kind,
        "version": version,
        "author": author,
        "description": description,
        "description_ar": description_ar,
        "files_root": "files",
        "files": manifest_files,
    }
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for rel_path, content in file_contents.items():
            zf.writestr(f"files/{rel_path}", content)
    return output_path


def build_sample_translation_zip(
    output_path: Path,
    *,
    extra_files: Mapping[str, bytes] | None = None,
) -> Path:
    files: dict[str, bytes] = {
        "localization/strings.txt": "MENU_PLAY=ابدأ اللعب\nMENU_SETTINGS=الإعدادات\n".encode(),
        "localization/fonts.cfg": b"font_family=SegoeUIArabic\nrtl=true\n",
    }
    if extra_files:
        files.update(extra_files)
    return _write_pack_zip(
        output_path,
        pkg_id="sample-arabic-translation",
        name="Sample Arabic Translation",
        name_ar="تعريب تجريبي عربي",
        kind="translation",
        version="1.0.0",
        author="GameRewind",
        description="Sample Arabic menus and subtitles pack for testing.",
        description_ar="حزمة تعريب تجريبية لاختبار القوائم والترجمة.",
        file_contents=files,
    )


def build_sample_mod_zip(
    output_path: Path,
    *,
    conflict_with_translation: bool = True,
) -> Path:
    files: dict[str, bytes] = {
        "ui/hud_theme.cfg": b"hud_scale=1.15\nminimal=true\n",
    }
    if conflict_with_translation:
        files["localization/fonts.cfg"] = b"font_family=ClassicHUD\nrtl=false\n"
    return _write_pack_zip(
        output_path,
        pkg_id="sample-classic-hud-mod",
        name="Sample Classic HUD Mod",
        name_ar="مود الواجهة الكلاسيكية التجريبي",
        kind="mod",
        version="2.0.0",
        author="GameRewind",
        description="Sample visual HUD mod for testing.",
        description_ar="مود تجريبي لتعديل شكل الواجهة.",
        file_contents=files,
    )
