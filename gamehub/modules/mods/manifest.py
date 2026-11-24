"""Strict declarative-only manifest and .zip validator for Translations & Mods.

Security guarantees:
- Zero scripts, commands, hooks, or executable payloads allowed.
- Zero path traversal ('..'), drive letters, UNC paths, absolute paths, null bytes,
  or Windows reserved device names.
- Zero zip symlinks, encrypted members, or zip bombs.
- Exact SHA-256 verification of every declared file before extraction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from gamehub.modules.mods.models import (
    ManifestValidationError,
    ModKind,
    ModManifest,
    ModManifestFile,
)

MAX_MANIFEST_BYTES = 256 * 1024
MAX_ZIP_FILES = 500
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

FORBIDDEN_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "cmd",
        "command",
        "commands",
        "exec",
        "execute",
        "hook",
        "hooks",
        "post_install",
        "post_uninstall",
        "powershell",
        "pre_install",
        "pre_uninstall",
        "run",
        "script",
        "scripts",
        "shell",
        "step",
        "steps",
    }
)

FORBIDDEN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".bash",
        ".bat",
        ".cmd",
        ".com",
        ".cpl",
        ".dll",
        ".drv",
        ".exe",
        ".hta",
        ".inf",
        ".js",
        ".jse",
        ".lnk",
        ".msi",
        ".msp",
        ".mst",
        ".ocx",
        ".pif",
        ".ps1",
        ".psd1",
        ".psm1",
        ".py",
        ".pyw",
        ".reg",
        ".scr",
        ".sh",
        ".sys",
        ".url",
        ".vbe",
        ".vbs",
        ".wsf",
        ".wsh",
    }
)

WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def normalize_rel_path(raw: str, *, allow_empty: bool = False) -> str:
    """Validate and normalize a relative POSIX path with strict Windows safety checks."""
    if not isinstance(raw, str):
        raise ManifestValidationError("Path must be a string.")
    if "\x00" in raw:
        raise ManifestValidationError("Path contains a null byte.")
    cleaned = raw.replace("\\", "/").strip()
    if not cleaned:
        if allow_empty:
            return ""
        raise ManifestValidationError("Path cannot be empty.")
    if cleaned.startswith(("/", "//")):
        raise ManifestValidationError(f"Absolute path is not allowed: {raw!r}")
    if ":" in cleaned:
        raise ManifestValidationError(f"Drive or stream path is not allowed: {raw!r}")

    parts = [part for part in cleaned.split("/") if part != ""]
    if not parts:
        if allow_empty:
            return ""
        raise ManifestValidationError("Path cannot be empty.")

    safe_parts: list[str] = []
    for part in parts:
        if part in {".", ".."}:
            raise ManifestValidationError(f"Path traversal is not allowed: {raw!r}")
        if part.endswith((".", " ")):
            raise ManifestValidationError(f"Invalid Windows path segment: {part!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise ManifestValidationError(f"Reserved Windows filename is not allowed: {part!r}")
        safe_parts.append(part)

    return PurePosixPath(*safe_parts).as_posix()


def _assert_safe_extension(rel_path: str) -> None:
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix in FORBIDDEN_EXTENSIONS:
        raise ManifestValidationError(
            f"Executable or script files are not allowed in packs: {rel_path!r}"
        )


def _assert_no_forbidden_keys(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).strip().lower() in FORBIDDEN_MANIFEST_KEYS:
                raise ManifestValidationError(
                    f"Scripts and command steps are not allowed in manifest.json ({key!r})."
                )
            _assert_no_forbidden_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_forbidden_keys(item)


def parse_manifest_dict(payload: object) -> ModManifest:
    """Validate a parsed manifest.json dictionary strictly."""
    if not isinstance(payload, dict):
        raise ManifestValidationError("manifest.json must be a JSON object.")
    _assert_no_forbidden_keys(payload)

    if payload.get("schema_version") != 1:
        raise ManifestValidationError("Unsupported manifest schema_version (expected 1).")

    pkg_id = str(payload.get("id", "")).strip()
    if not _ID_RE.fullmatch(pkg_id):
        raise ManifestValidationError("manifest.json has an invalid package id.")

    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 120:
        raise ManifestValidationError("manifest.json must include a valid package name.")
    name_ar = str(payload.get("name_ar") or name).strip()[:120]

    raw_kind = str(payload.get("kind", "")).strip().lower()
    if raw_kind in {"translation", "arabization"}:
        kind: ModKind = "translation"
    elif raw_kind == "mod":
        kind = "mod"
    else:
        raise ManifestValidationError("manifest.json kind must be 'translation' or 'mod'.")

    version = str(payload.get("version", "1.0.0")).strip()[:40] or "1.0.0"
    author = str(payload.get("author", "")).strip()[:80]
    description = str(payload.get("description", "")).strip()[:400]
    description_ar = str(payload.get("description_ar") or description).strip()[:400]

    files_root = normalize_rel_path(str(payload.get("files_root", "files")), allow_empty=True)

    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ManifestValidationError("manifest.json must list at least one file.")
    if len(raw_files) > MAX_ZIP_FILES:
        raise ManifestValidationError("Package exceeds the maximum allowed file count.")

    parsed_files: list[ModManifestFile] = []
    seen_dests: set[str] = set()
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ManifestValidationError("Each file entry in manifest.json must be an object.")
        src = normalize_rel_path(str(entry.get("src", "")))
        dest = normalize_rel_path(str(entry.get("dest", "")))
        _assert_safe_extension(src)
        _assert_safe_extension(dest)
        sha = str(entry.get("sha256", "")).strip().lower()
        if not _SHA256_RE.fullmatch(sha):
            raise ManifestValidationError(f"Invalid sha256 checksum for {dest!r}.")
        dest_key = dest.casefold()
        if dest_key in seen_dests:
            raise ManifestValidationError(f"Duplicate target file in manifest: {dest!r}")
        seen_dests.add(dest_key)
        parsed_files.append(ModManifestFile(src=src, dest=dest, sha256=sha))

    return ModManifest(
        schema_version=1,
        id=pkg_id,
        name=name,
        name_ar=name_ar,
        kind=kind,
        version=version,
        author=author,
        description=description,
        description_ar=description_ar,
        files_root=files_root,
        files=tuple(parsed_files),
    )


def manifest_to_json(manifest: ModManifest) -> str:
    return json.dumps(
        {
            "schema_version": manifest.schema_version,
            "id": manifest.id,
            "name": manifest.name,
            "name_ar": manifest.name_ar,
            "kind": manifest.kind,
            "version": manifest.version,
            "author": manifest.author,
            "description": manifest.description,
            "description_ar": manifest.description_ar,
            "files_root": manifest.files_root,
            "files": [
                {"src": f.src, "dest": f.dest, "sha256": f.sha256} for f in manifest.files
            ],
        },
        ensure_ascii=False,
    )


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(unix_mode)


def _zip_member_key(files_root: str, src: str) -> str:
    return f"{files_root}/{src}" if files_root else src


def _inspect_zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_FILES + 50:
        raise ManifestValidationError("Archive contains too many entries.")
    total_size = 0
    by_name: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if info.flag_bits & 0x1:
            raise ManifestValidationError("Encrypted .zip archives are not supported.")
        if _is_zip_symlink(info):
            raise ManifestValidationError("Symbolic links inside .zip archives are not allowed.")
        if info.is_dir():
            continue
        norm = normalize_rel_path(info.filename)
        if norm.lower() != "manifest.json":
            _assert_safe_extension(norm)
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            raise ManifestValidationError(f"Archive member exceeds size limit: {norm!r}")
        total_size += info.file_size
        if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ManifestValidationError("Archive uncompressed size exceeds safety limit.")
        if norm in by_name:
            raise ManifestValidationError(f"Archive contains duplicate path: {norm!r}")
        by_name[norm] = info
    return by_name


def validate_zip_manifest(zip_path: Path) -> ModManifest:
    """Validate a .zip pack's manifest and verify SHA-256 of every declared member."""
    if not zip_path.is_file():
        raise ManifestValidationError("Selected .zip file does not exist.")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = _inspect_zip_members(archive)
            manifest_info = members.get("manifest.json")
            if manifest_info is None:
                raise ManifestValidationError("The .zip file is missing manifest.json.")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise ManifestValidationError("manifest.json is too large.")
            try:
                raw_manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ManifestValidationError("manifest.json is not valid UTF-8 JSON.") from exc

            manifest = parse_manifest_dict(raw_manifest)
            for item in manifest.files:
                member_name = _zip_member_key(manifest.files_root, item.src)
                info = members.get(member_name)
                if info is None:
                    raise ManifestValidationError(
                        f"Declared file is missing from the .zip archive: {member_name!r}"
                    )
                digest = hashlib.sha256()
                read_bytes = 0
                with archive.open(info, "r") as src_stream:
                    while True:
                        chunk = src_stream.read(128 * 1024)
                        if not chunk:
                            break
                        read_bytes += len(chunk)
                        if read_bytes > MAX_SINGLE_FILE_BYTES:
                            raise ManifestValidationError("Archive member exceeded size limit.")
                        digest.update(chunk)
                if digest.hexdigest() != item.sha256:
                    raise ManifestValidationError(
                        f"Checksum mismatch for {item.dest!r}; the package may be damaged."
                    )
            return manifest
    except zipfile.BadZipFile as exc:
        raise ManifestValidationError("The selected file is not a valid .zip archive.") from exc


def extract_verified_package(zip_path: Path, dest_dir: Path) -> ModManifest:
    """Validate and extract ONLY declared files into dest_dir/files with SHA-256 verification."""
    manifest = validate_zip_manifest(zip_path)
    files_dir = dest_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = _inspect_zip_members(archive)
        for item in manifest.files:
            member_name = _zip_member_key(manifest.files_root, item.src)
            info = members[member_name]
            out_path = files_dir.joinpath(*PurePosixPath(item.dest).parts)
            # Belt-and-suspenders containment check inside dest_dir/files
            resolved_root = files_dir.resolve()
            resolved_out = out_path.resolve()
            if not resolved_out.is_relative_to(resolved_root):
                raise ManifestValidationError("Extraction path escaped package directory.")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with archive.open(info, "r") as src_stream, out_path.open("wb") as dst_stream:
                while True:
                    chunk = src_stream.read(128 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    dst_stream.write(chunk)
                dst_stream.flush()
                os.fsync(dst_stream.fileno())
            if digest.hexdigest() != item.sha256:
                raise ManifestValidationError(f"Checksum mismatch while extracting {item.dest!r}.")
    (dest_dir / "manifest.json").write_text(manifest_to_json(manifest), encoding="utf-8")
    return manifest
