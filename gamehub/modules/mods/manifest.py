"""Strict declarative-only manifest and .zip validator for Translations & Mods.

Security guarantees:
- Zero scripts, commands, hooks, or executable/PE payloads allowed.
- Zero path traversal ('..'), drive letters, UNC paths, absolute paths, null/control/BiDi chars,
  Windows reserved device names, or file-vs-directory collisions.
- Zero zip symlinks, encrypted members, case-duplicate entries, or src-reuse zip bombs.
- Iterative JSON inspection (immune to RecursionError) + bounded manifest stream read.
- Exact SHA-256 verification of every declared file before extraction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
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
MAX_REL_PATH_LEN = 240

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INVALID_WIN_CHARS = re.compile(r'[\x00-\x1f<>:"|?*\u202a-\u202e\u2066-\u2069]')
_DEVICE_STEM = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$",
    re.IGNORECASE,
)

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
        ".appinstaller",
        ".application",
        ".appx",
        ".appxbundle",
        ".asi",
        ".bash",
        ".bat",
        ".cab",
        ".chm",
        ".cjs",
        ".cmd",
        ".com",
        ".cpl",
        ".diagcab",
        ".dll",
        ".docm",
        ".drv",
        ".exe",
        ".flt",
        ".gadget",
        ".hta",
        ".img",
        ".inf",
        ".iso",
        ".jar",
        ".jnlp",
        ".js",
        ".jse",
        ".library-ms",
        ".lnk",
        ".m3d",
        ".mix",
        ".mjs",
        ".msc",
        ".msi",
        ".msix",
        ".msixbundle",
        ".msp",
        ".mst",
        ".ocx",
        ".pif",
        ".ps1",
        ".ps1xml",
        ".psd1",
        ".psm1",
        ".py",
        ".pyc",
        ".pyd",
        ".pyo",
        ".pyw",
        ".reg",
        ".scf",
        ".scr",
        ".sct",
        ".searchconnector-ms",
        ".settingcontent-ms",
        ".sh",
        ".sys",
        ".url",
        ".vb",
        ".vba",
        ".vbe",
        ".vbs",
        ".vhd",
        ".vhdx",
        ".ws",
        ".wsc",
        ".wsf",
        ".wsh",
        ".xll",
        ".xlsm",
    }
)


class _StreamingPeDetector:
    """Detect Windows PE executables/DLLs (MZ + PE\\0\\0 at ANY e_lfanew offset) while streaming."""

    def __init__(self) -> None:
        self._pos = 0
        self._dos_head = bytearray()
        self._pe_offset: int | None = None
        self._sig_buf = bytearray()
        self.is_pe = False

    def feed(self, chunk: bytes) -> None:
        if self.is_pe or not chunk:
            return
        start = self._pos
        end = start + len(chunk)
        self._pos = end

        if len(self._dos_head) < 64:
            need = 64 - len(self._dos_head)
            self._dos_head.extend(chunk[:need])
            if len(self._dos_head) >= 2 and self._dos_head[:2] != b"MZ":
                self._pe_offset = -1
                return
            if len(self._dos_head) >= 64:
                self._pe_offset = struct.unpack_from("<I", self._dos_head, 60)[0]
                if self._pe_offset < 64 or self._pe_offset > MAX_SINGLE_FILE_BYTES:
                    self._pe_offset = -1
                    return

        if self._pe_offset is None or self._pe_offset < 0:
            return

        sig_start = self._pe_offset
        sig_end = sig_start + 4
        if end > sig_start and start < sig_end:
            overlap_start = max(start, sig_start)
            overlap_end = min(end, sig_end)
            self._sig_buf.extend(chunk[overlap_start - start : overlap_end - start])
            if len(self._sig_buf) >= 4:
                if bytes(self._sig_buf[:4]) == b"PE\x00\x00":
                    self.is_pe = True
                self._pe_offset = -1


def normalize_rel_path(raw: str, *, allow_empty: bool = False) -> str:
    """Validate and normalize a relative POSIX path with strict Windows safety checks."""
    if not isinstance(raw, str):
        raise ManifestValidationError("Path must be a string.")
    if _INVALID_WIN_CHARS.search(raw):
        raise ManifestValidationError(f"Path contains forbidden Windows or control characters: {raw!r}")
    cleaned = raw.replace("\\", "/").strip()
    if not cleaned:
        if allow_empty:
            return ""
        raise ManifestValidationError("Path cannot be empty.")
    if len(cleaned) > MAX_REL_PATH_LEN:
        raise ManifestValidationError("Path exceeds maximum safe Windows length.")
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
        stem = part.partition(".")[0].rstrip(" ")
        if _DEVICE_STEM.fullmatch(stem):
            raise ManifestValidationError(f"Reserved Windows filename is not allowed: {part!r}")
        safe_parts.append(part)

    return PurePosixPath(*safe_parts).as_posix()


def _assert_safe_extension(rel_path: str) -> None:
    suffix = PurePosixPath(rel_path).suffix.lower()
    if suffix in FORBIDDEN_EXTENSIONS:
        raise ManifestValidationError(
            f"Executable or script files are not allowed in packs: {rel_path!r}"
        )


def _assert_no_forbidden_keys(root: Any) -> None:
    """Iterative traversal so deeply nested JSON cannot trigger RecursionError."""
    stack: list[Any] = [root]
    visited = 0
    while stack:
        current = stack.pop()
        visited += 1
        if visited > 50_000:
            raise ManifestValidationError("manifest.json structure is too complex.")
        if isinstance(current, dict):
            for key, value in current.items():
                if str(key).strip().lower() in FORBIDDEN_MANIFEST_KEYS:
                    raise ManifestValidationError(
                        f"Scripts and command steps are not allowed in manifest.json ({key!r})."
                    )
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    stack.append(item)


def _assert_no_path_prefix_collisions(paths: list[str]) -> None:
    """Reject sets where one path is both a file and a parent directory (case-insensitive)."""
    dir_prefixes: set[str] = set()
    file_keys: set[str] = set()
    for p in paths:
        parts = p.casefold().split("/")
        file_keys.add("/".join(parts))
        for idx in range(1, len(parts)):
            dir_prefixes.add("/".join(parts[:idx]))
    if file_keys & dir_prefixes:
        raise ManifestValidationError("Package contains conflicting file and directory paths.")


def parse_manifest_dict(payload: object) -> ModManifest:
    """Validate a parsed manifest.json dictionary strictly."""
    if not isinstance(payload, dict):
        raise ManifestValidationError("manifest.json must be a JSON object.")
    _assert_no_forbidden_keys(payload)

    schema_ver = payload.get("schema_version")
    if type(schema_ver) is not int or schema_ver != 1:
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

    _assert_no_path_prefix_collisions([f.dest for f in parsed_files])

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
    return (f"{files_root}/{src}" if files_root else src).casefold()


def _inspect_zip_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_FILES + 50:
        raise ManifestValidationError("Archive contains too many entries.")
    total_size = 0
    by_casefold: dict[str, zipfile.ZipInfo] = {}
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
        key = norm.casefold()
        if key in by_casefold:
            raise ManifestValidationError(f"Archive contains case-duplicate path: {norm!r}")
        by_casefold[key] = info
    return by_casefold


def validate_zip_manifest(zip_path: Path) -> ModManifest:
    """Validate a .zip pack's manifest and verify SHA-256 + non-PE content of every declared member."""
    if not zip_path.is_file():
        raise ManifestValidationError("Selected .zip file does not exist.")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = _inspect_zip_members(archive)
            manifest_info = members.get("manifest.json")
            if manifest_info is None:
                raise ManifestValidationError("The .zip file is missing manifest.json.")
            with archive.open(manifest_info, "r") as m_stream:
                raw_bytes = m_stream.read(MAX_MANIFEST_BYTES + 1)
            if len(raw_bytes) > MAX_MANIFEST_BYTES:
                raise ManifestValidationError("manifest.json is too large.")
            try:
                raw_manifest = json.loads(raw_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                raise ManifestValidationError("manifest.json is not valid UTF-8 JSON.") from exc

            manifest = parse_manifest_dict(raw_manifest)
            total_declared_bytes = 0
            for item in manifest.files:
                member_key = _zip_member_key(manifest.files_root, item.src)
                info = members.get(member_key)
                if info is None:
                    raise ManifestValidationError(
                        f"Declared file is missing from the .zip archive: {item.src!r}"
                    )
                digest = hashlib.sha256()
                read_bytes = 0
                pe_detector = _StreamingPeDetector()
                with archive.open(info, "r") as src_stream:
                    while True:
                        chunk = src_stream.read(128 * 1024)
                        if not chunk:
                            break
                        pe_detector.feed(chunk)
                        if pe_detector.is_pe:
                            raise ManifestValidationError(
                                f"Executable PE binary payload is not allowed: {item.dest!r}"
                            )
                        read_bytes += len(chunk)
                        total_declared_bytes += len(chunk)
                        if read_bytes > MAX_SINGLE_FILE_BYTES:
                            raise ManifestValidationError("Archive member exceeded size limit.")
                        if total_declared_bytes > MAX_TOTAL_UNCOMPRESSED_BYTES:
                            raise ManifestValidationError(
                                "Total declared output size exceeds safety limit."
                            )
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
            member_key = _zip_member_key(manifest.files_root, item.src)
            info = members[member_key]
            out_path = files_dir.joinpath(*PurePosixPath(item.dest).parts)
            resolved_root = files_dir.resolve()
            resolved_out = out_path.resolve()
            if not resolved_out.is_relative_to(resolved_root):
                raise ManifestValidationError("Extraction path escaped package directory.")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            pe_detector = _StreamingPeDetector()
            with archive.open(info, "r") as src_stream, out_path.open("wb") as dst_stream:
                while True:
                    chunk = src_stream.read(128 * 1024)
                    if not chunk:
                        break
                    pe_detector.feed(chunk)
                    digest.update(chunk)
                    dst_stream.write(chunk)
                dst_stream.flush()
                os.fsync(dst_stream.fileno())
            if pe_detector.is_pe or digest.hexdigest() != item.sha256:
                out_path.unlink(missing_ok=True)
                raise ManifestValidationError(f"Verification failed while extracting {item.dest!r}.")
    (dest_dir / "manifest.json").write_text(manifest_to_json(manifest), encoding="utf-8")
    return manifest
