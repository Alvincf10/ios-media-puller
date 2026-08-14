#!/usr/bin/env python3
"""
Best-effort purge artifact extraction from Photos.sqlite (+ WAL).

Research-backed: after permanent delete from Recently Deleted, full media is gone,
but metadata often lingers in:
  - ACHANGE tombstone columns (UUID + expunge reason + timestamps)
  - Photos.sqlite-wal packed asset records (UUID + directory + filename + UTI)

This recovers *evidence of purged assets*, not original media bytes.

Authorization: Authorized security research / own-device lab use only.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("photos_purge_artifacts")

# Packed WAL form: <UUID><DIR><FILENAME> then optional UTI
WAL_ASSET_RE = re.compile(
    rb"([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})"
    rb"(DCIM/\d+APPLE|PhotoData/CPLAssets/group\d{1,3})"
    rb"((?:IMG_[0-9A-Za-z_]+|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})\."
    rb"(?:HEIC|heic|HEIF|heif|MOV|mov|MP4|mp4|M4V|m4v|"
    rb"JPG|jpg|JPEG|jpeg|PNG|png|JXL|jxl|GIF|gif|DNG|dng|TIF|tif|TIFF|tiff|WEBP|webp))"
)
UTI_AFTER_RE = re.compile(rb"^(com\.apple\.[a-z][a-z0-9.\-]*)")
UUID_TEXT_RE = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)

# Apple epoch: seconds since 2001-01-01 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


@dataclass
class PurgeArtifact:
    uuid: str
    filename: str | None = None
    directory: str | None = None
    remote_path: str | None = None
    uti: str | None = None
    sources: list[str] = field(default_factory=list)
    expunge_reason: str | None = None
    trashed_date_apple: float | None = None
    trashed_date_iso: str | None = None
    achange_pk: int | None = None
    still_in_zasset: bool = False
    wal_hit_count: int = 0

    def merge(self, other: "PurgeArtifact") -> None:
        if not self.filename and other.filename:
            self.filename = other.filename
        if not self.directory and other.directory:
            self.directory = other.directory
        if not self.remote_path and other.remote_path:
            self.remote_path = other.remote_path
        if not self.uti and other.uti:
            self.uti = other.uti
        if not self.expunge_reason and other.expunge_reason:
            self.expunge_reason = other.expunge_reason
        if self.trashed_date_apple is None and other.trashed_date_apple is not None:
            self.trashed_date_apple = other.trashed_date_apple
            self.trashed_date_iso = other.trashed_date_iso
        if self.achange_pk is None and other.achange_pk is not None:
            self.achange_pk = other.achange_pk
        self.still_in_zasset = self.still_in_zasset or other.still_in_zasset
        self.wal_hit_count = max(self.wal_hit_count, other.wal_hit_count)
        for s in other.sources:
            if s not in self.sources:
                self.sources.append(s)


def _format_apple_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(APPLE_EPOCH.timestamp() + float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _pick_asset_table(conn: sqlite3.Connection) -> str:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for candidate in ("ZASSET", "ZGENERICASSET"):
        if candidate in names:
            return candidate
    raise RuntimeError("ZASSET/ZGENERICASSET tidak ditemukan")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _current_assets(conn: sqlite3.Connection) -> dict[str, dict]:
    """uuid -> {filename, directory, trashed} for live ZASSET rows."""
    table = _pick_asset_table(conn)
    cols = _table_columns(conn, table)
    if "ZUUID" not in cols:
        return {}
    parts = ["ZUUID", "ZFILENAME", "ZDIRECTORY"]
    trashed = "ZTRASHEDSTATE" if "ZTRASHEDSTATE" in cols else None
    if trashed:
        parts.append(trashed)
    sql = f'SELECT {", ".join(parts)} FROM {table} WHERE ZUUID IS NOT NULL'
    out: dict[str, dict] = {}
    for row in conn.execute(sql):
        uuid = row[0]
        if not uuid:
            continue
        out[str(uuid).upper()] = {
            "filename": row[1],
            "directory": row[2],
            "trashed": int(row[3] or 0) if trashed else 0,
        }
    return out


def _parse_achange_tombstones(conn: sqlite3.Connection) -> dict[str, PurgeArtifact]:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "ACHANGE" not in names:
        logger.info("Tabel ACHANGE tidak ada — skip tombstone parse")
        return {}
    cols = _table_columns(conn, "ACHANGE")
    tomb_cols = [
        c
        for c in (
            "ZTOMBSTONE0",
            "ZTOMBSTONE1",
            "ZTOMBSTONE2",
            "ZTOMBSTONE3",
            "ZTOMBSTONE4",
            "ZTOMBSTONE5",
        )
        if c in cols
    ]
    if "ZTOMBSTONE0" not in tomb_cols:
        return {}

    select = ["Z_PK", *tomb_cols]
    rows = conn.execute(
        f'SELECT {", ".join(select)} FROM ACHANGE WHERE ZTOMBSTONE0 IS NOT NULL'
    ).fetchall()
    artifacts: dict[str, PurgeArtifact] = {}
    for row in rows:
        pk = row[0]
        values = {tomb_cols[i]: row[i + 1] for i in range(len(tomb_cols))}
        uuid_raw = values.get("ZTOMBSTONE0")
        if not uuid_raw or not isinstance(uuid_raw, str):
            continue
        if not UUID_TEXT_RE.fullmatch(str(uuid_raw)):
            continue
        uuid = str(uuid_raw).upper()
        reason = values.get("ZTOMBSTONE2")
        reason_s = str(reason) if reason is not None else None

        interesting = False
        if reason_s and any(k in reason_s.lower() for k in ("expunge", "deleted", "trash", "delete")):
            interesting = True
        if values.get("ZTOMBSTONE5") and str(values.get("ZTOMBSTONE5")).upper() == uuid:
            interesting = True
        if reason_s is None:
            interesting = True
        if not interesting:
            continue

        trashed_date = None
        raw_date = values.get("ZTOMBSTONE3")
        if isinstance(raw_date, (int, float)):
            trashed_date = float(raw_date)
        elif isinstance(raw_date, str):
            try:
                trashed_date = float(raw_date)
            except ValueError:
                trashed_date = None

        art = PurgeArtifact(
            uuid=uuid,
            sources=["ACHANGE.tombstone"],
            expunge_reason=reason_s,
            trashed_date_apple=trashed_date,
            trashed_date_iso=_format_apple_ts(trashed_date),
            achange_pk=int(pk) if pk is not None else None,
        )
        if uuid in artifacts:
            artifacts[uuid].merge(art)
        else:
            artifacts[uuid] = art
    return artifacts


def _parse_wal_assets(wal_path: Path) -> dict[str, PurgeArtifact]:
    if not wal_path.exists():
        return {}
    data = wal_path.read_bytes()
    artifacts: dict[str, PurgeArtifact] = {}
    for m in WAL_ASSET_RE.finditer(data):
        uuid = m.group(1).decode("ascii").upper()
        directory = m.group(2).decode("ascii", "ignore")
        filename = m.group(3).decode("ascii", "ignore")
        uti = None
        rest = data[m.end() : m.end() + 80]
        um = UTI_AFTER_RE.match(rest)
        if um:
            uti = um.group(1).decode("ascii", "ignore")
            # Bound UTI if next UUID digits were glued (...movie35B517DD-...)
            uti = re.sub(r"[0-9]+$", "", uti)
            if not uti.startswith("com.apple."):
                uti = None
        remote = f"/{directory.strip('/')}/{filename}"
        art = PurgeArtifact(
            uuid=uuid,
            filename=filename,
            directory=directory,
            remote_path=remote,
            uti=uti,
            sources=["Photos.sqlite-wal"],
            wal_hit_count=1,
        )
        if uuid in artifacts:
            artifacts[uuid].wal_hit_count += 1
            artifacts[uuid].merge(art)
        else:
            artifacts[uuid] = art
    return artifacts


def _parse_background_jobs(conn: sqlite3.Connection) -> dict[str, PurgeArtifact]:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "ZBACKGROUNDJOBWORKITEM" not in names:
        return {}
    cols = _table_columns(conn, "ZBACKGROUNDJOBWORKITEM")
    if "ZIDENTIFIER" not in cols:
        return {}
    artifacts: dict[str, PurgeArtifact] = {}
    for (ident,) in conn.execute(
        "SELECT ZIDENTIFIER FROM ZBACKGROUNDJOBWORKITEM WHERE ZIDENTIFIER IS NOT NULL"
    ):
        s = str(ident)
        if not UUID_TEXT_RE.fullmatch(s):
            continue
        uuid = s.upper()
        artifacts[uuid] = PurgeArtifact(uuid=uuid, sources=["ZBACKGROUNDJOBWORKITEM"])
    return artifacts


def extract_purge_artifacts(db_path: Path) -> list[PurgeArtifact]:
    """Parse Photos.sqlite (+ sibling -wal) for purged-asset evidence."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        live = _current_assets(conn)
        live_filenames = {v["filename"] for v in live.values() if v.get("filename")}
        by_uuid: dict[str, PurgeArtifact] = {}

        def absorb(src: dict[str, PurgeArtifact]) -> None:
            for uuid, art in src.items():
                if uuid in by_uuid:
                    by_uuid[uuid].merge(art)
                else:
                    by_uuid[uuid] = art

        absorb(_parse_achange_tombstones(conn))
        absorb(_parse_background_jobs(conn))
        absorb(_parse_wal_assets(db_path.parent / "Photos.sqlite-wal"))

        for uuid, art in by_uuid.items():
            if uuid in live:
                art.still_in_zasset = True
                if not art.filename:
                    art.filename = live[uuid].get("filename")
                if not art.directory:
                    art.directory = live[uuid].get("directory")
                if art.filename and art.directory and not art.remote_path:
                    art.remote_path = f"/{str(art.directory).strip('/')}/{art.filename}"
            elif art.filename and art.filename in live_filenames:
                # WAL may reuse/glitch UUID mapping; filename still live → not purged.
                art.still_in_zasset = True

        items = list(by_uuid.values())
        items.sort(
            key=lambda a: (
                a.still_in_zasset,
                -(a.trashed_date_apple or 0),
                a.filename or "",
                a.uuid,
            )
        )
        return items
    finally:
        conn.close()


def write_purge_report(artifacts: list[PurgeArtifact], out_dir: Path) -> dict:
    """Write JSON/CSV/TXT report. Returns summary counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    purged = [a for a in artifacts if not a.still_in_zasset]
    still = [a for a in artifacts if a.still_in_zasset]
    with_name = [a for a in purged if a.filename]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Metadata evidence only — not recoverable full media. "
            "Rows with still_in_zasset=false are candidates for permanent purge."
        ),
        "summary": {
            "total_uuids": len(artifacts),
            "purged_not_in_zasset": len(purged),
            "purged_with_filename": len(with_name),
            "still_in_zasset": len(still),
        },
        "purged": [asdict(a) for a in purged],
        "still_in_library_or_trash": [asdict(a) for a in still],
    }
    (out_dir / "purge_artifacts.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    fields = [
        "uuid",
        "filename",
        "directory",
        "remote_path",
        "uti",
        "still_in_zasset",
        "expunge_reason",
        "trashed_date_iso",
        "wal_hit_count",
        "sources",
        "achange_pk",
    ]
    with (out_dir / "purge_artifacts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for a in artifacts:
            row = asdict(a)
            row["sources"] = "|".join(a.sources)
            w.writerow({k: row.get(k) for k in fields})

    lines = [
        "Photos purge artifacts (metadata only)",
        f"generated: {payload['generated_at']}",
        f"purged (not in ZASSET): {len(purged)} | with filename: {len(with_name)} | still present: {len(still)}",
        "",
        "=== PURGED (not in ZASSET) ===",
    ]
    for a in purged:
        lines.append(
            f"- {a.filename or '(unknown filename)'} | {a.remote_path or '-'} | "
            f"uuid={a.uuid} | date={a.trashed_date_iso or '-'} | "
            f"src={','.join(a.sources)}"
        )
        if a.expunge_reason:
            lines.append(f"    reason: {a.expunge_reason}")
    lines.append("")
    lines.append("=== STILL IN ZASSET (library or Recently Deleted) ===")
    for a in still:
        lines.append(
            f"- {a.filename or '(unknown)'} | uuid={a.uuid} | src={','.join(a.sources)}"
        )
    (out_dir / "purge_artifacts.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    logger.info(
        "Purge artifacts: purged=%d (named=%d) still_present=%d → %s",
        len(purged),
        len(with_name),
        len(still),
        out_dir.resolve(),
    )
    return payload["summary"]


_ORIGINAL_EXTS = {".heic", ".heif", ".mov", ".mp4", ".m4v", ".jpg", ".jpeg", ".png", ".jxl"}
_PREVIEW_HINTS = ("5005.jpg", "localvideokeyframe.jpg", "_carve_")


def _quality_rank(path: Path) -> tuple[int, int]:
    """Higher is better: real original media > jpeg preview."""
    name = path.name.lower()
    ext = path.suffix.lower()
    size = path.stat().st_size if path.exists() else 0
    if any(h in name for h in _PREVIEW_HINTS) or name.endswith(".jpg"):
        return (0, size)
    if ext in {".heic", ".heif", ".mov", ".mp4", ".m4v"}:
        return (2, size)
    if ext in _ORIGINAL_EXTS:
        return (1, size)
    return (0, size)


def _find_candidates(filename: str, search_roots: list[Path]) -> list[Path]:
    needle = filename.lower()
    hits: list[Path] = []
    seen: set[str] = set()
    skip_parts = {"reconstructed", "purge_metadata", "photos_db", "ithmb_carved"}
    for root in search_roots:
        root = Path(root)
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in skip_parts for part in p.parts):
                continue
            low = p.name.lower()
            if needle not in low:
                continue
            if p.suffix.lower() in {".json", ".csv", ".txt", ".ithmb", ".sqlite", ".wal", ".shm"}:
                continue
            try:
                key = str(p.resolve())
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            hits.append(p)
    hits.sort(key=_quality_rank, reverse=True)
    return hits


def correlate_and_restore(
    artifacts: list[PurgeArtifact],
    out_dir: Path,
    search_roots: list[Path],
) -> dict:
    """Write the purged-asset knowledge report.

    Primary output is the list of assets that were permanently deleted
    (even if we never saw the file beforehand). Optional copies go into
    originals/previews only when a leftover file exists on disk.
    """
    restored_dir = out_dir / "reconstructed"
    originals_dir = restored_dir / "originals"
    previews_dir = restored_dir / "previews"
    restored_dir.mkdir(parents=True, exist_ok=True)
    originals_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)

    purged = [a for a in artifacts if not a.still_in_zasset]
    named = [a for a in purged if a.filename]
    unknown = [a for a in purged if not a.filename]

    rows: list[dict] = []
    n_orig = n_prev = n_miss = 0
    for art in named:
        cands = _find_candidates(art.filename or "", search_roots)
        best = cands[0] if cands else None
        kind = "metadata_only"
        dest: str | None = None
        if best is not None:
            rank, _ = _quality_rank(best)
            if rank >= 1:
                dest_path = originals_dir / art.filename  # type: ignore[arg-type]
                kind = "original_copy"
                n_orig += 1
            else:
                dest_path = previews_dir / f"{art.filename}__preview.jpg"
                kind = "jpeg_preview"
                n_prev += 1
            if not (dest_path.exists() and dest_path.stat().st_size == best.stat().st_size):
                shutil.copy2(best, dest_path)
            dest = str(dest_path)
        else:
            n_miss += 1
        rows.append(
            {
                "uuid": art.uuid,
                "filename": art.filename,
                "remote_path": art.remote_path,
                "expunge_reason": art.expunge_reason,
                "trashed_date_iso": art.trashed_date_iso,
                "match_kind": kind,
                "source_file": str(best) if best else None,
                "restored_to": dest,
            }
        )

    known_lines = [
        "FILE YANG SUDAH DI-PURGE (ketahuan dari Photos.sqlite tombstone/WAL)",
        "Ini bukti hapus permanen meskipun kita tidak sempat tarik filenya dulu.",
        "Byte HEIC asli di HP sudah hilang; yang tersisa adalah identitas file.",
        "",
        f"bernama={len(named)}  tanpa nama (UUID only)={len(unknown)}",
        "",
        "=== BERNAMA ===",
    ]
    for a in named:
        known_lines.append(
            f"{a.filename}\t{a.remote_path or '-'}\tuuid={a.uuid}\t"
            f"deleted={a.trashed_date_iso or '-'}"
        )
        if a.expunge_reason:
            known_lines.append(f"    {a.expunge_reason}")
    known_lines += ["", "=== TANPA NAMA (tetap ketahuan terhapus) ==="]
    for a in unknown:
        known_lines.append(
            f"uuid={a.uuid}\tdeleted={a.trashed_date_iso or '-'}\t"
            f"reason={(a.expunge_reason or '-')[:80]}"
        )
    (restored_dir / "DELETED_KNOWN.txt").write_text("\n".join(known_lines) + "\n", encoding="utf-8")

    unknown_lines = [
        "Asset terhapus permanen tanpa filename di WAL.",
        "Masih bisa diketahui: UUID + waktu + alasan expunge.",
        "",
    ]
    for a in unknown:
        unknown_lines.append(f"{a.uuid}\t{a.trashed_date_iso or '-'}")
        if a.expunge_reason:
            unknown_lines.append(f"    {a.expunge_reason}")
    (restored_dir / "DELETED_UNKNOWN_UUID.txt").write_text(
        "\n".join(unknown_lines) + "\n", encoding="utf-8"
    )

    index = {
        "note": (
            "Yang bisa diketahui setelah purge tanpa tarik sebelumnya: "
            "nama/path/UUID/waktu/alasan (DELETED_KNOWN.txt). "
            "File HEIC utuh hanya ada jika sempat tersalin sebelum purge."
        ),
        "summary": {
            "purged_total": len(purged),
            "purged_named": len(named),
            "purged_unknown_uuid": len(unknown),
            "restored_originals": n_orig,
            "restored_previews": n_prev,
            "named_without_file": n_miss,
        },
        "named_items": rows,
        "unknown_uuids": [
            {
                "uuid": a.uuid,
                "trashed_date_iso": a.trashed_date_iso,
                "expunge_reason": a.expunge_reason,
            }
            for a in unknown
        ],
    }
    (restored_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    (restored_dir / "index.txt").write_text(
        "\n".join(
            [
                "Jejak hapus permanen (bukan undelete HEIC)",
                index["note"],
                "",
                f"purged bernama : {len(named)}",
                f"purged UUID only: {len(unknown)}",
                f"salinan original: {n_orig}",
                f"preview JPEG    : {n_prev}",
                "",
                "Buka DELETED_KNOWN.txt untuk daftar file yang ketahuan terhapus.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    logger.info(
        "Jejak purge: named=%d uuid_only=%d copies=%d previews=%d → %s",
        len(named),
        len(unknown),
        n_orig,
        n_prev,
        restored_dir.resolve(),
    )
    return index["summary"]
