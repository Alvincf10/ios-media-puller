#!/usr/bin/env python3
"""
Pull frequently viewed/played photos & videos from iOS.

View/play counts live in /PhotoData/Photos.sqlite (not in DCIM file mtime).
This script:
  1) pulls Photos.sqlite (+ WAL/SHM) via AFC
  2) ranks assets by ZVIEWCOUNT / ZPLAYCOUNT (+ pending counts)
  3) downloads matching media files
  4) always also downloads Hidden + Recently Deleted into subfolders
  5) best-effort: leftover thumbnail / .ithmb previews for purged originals
  6) WAL/tombstone parse → metadata report of permanently purged assets

Device must be unlocked + trusted.
Authorization: Authorized security research / own-device lab use only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pull_frequent_media")

PHOTO_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".dng", ".tif", ".tiff", ".gif", ".webp", ".jxl"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".3gp"}
PHOTO_DB_FILES = ("Photos.sqlite", "Photos.sqlite-wal", "Photos.sqlite-shm")
THUMB_V2_ROOT = "/PhotoData/Thumbnails/V2"
THUMB_ITHMB_DIR = "/PhotoData/Thumbnails"
VIDEO_KEYFRAME_ROOT = "/PhotoData/Thumbnails/VideoKeyFrames"
JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"


@dataclass
class RankedAsset:
    remote_path: str
    filename: str
    views: int
    plays: int
    favorite: int
    hidden: int
    trashed: int
    kind: str

    @property
    def score(self) -> int:
        return self.views + self.plays


def _classify(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1] for r in rows}


def _pick_asset_table(conn: sqlite3.Connection) -> str:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for candidate in ("ZASSET", "ZGENERICASSET"):
        if candidate in names:
            return candidate
    raise RuntimeError("Tidak menemukan tabel ZASSET/ZGENERICASSET di Photos.sqlite")


def _query_ranked(
    db_path: Path,
    min_score: int,
    favorites_only: bool = False,
    hidden_only: bool = False,
    trashed_only: bool = False,
) -> list[dict]:
    """Return ranked rows from Photos.sqlite with defensive column detection."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        asset_table = _pick_asset_table(conn)
        asset_cols = _table_columns(conn, asset_table)
        add_cols = _table_columns(conn, "ZADDITIONALASSETATTRIBUTES")

        required_asset = {"ZDIRECTORY", "ZFILENAME"}
        if not required_asset.issubset(asset_cols):
            raise RuntimeError(f"{asset_table} missing ZDIRECTORY/ZFILENAME: {sorted(asset_cols)[:30]}")

        # Join key: ZASSET.ZADDITIONALATTRIBUTES -> ZADDITIONALASSETATTRIBUTES.Z_PK
        join_col = "ZADDITIONALATTRIBUTES" if "ZADDITIONALATTRIBUTES" in asset_cols else None
        if join_col is None:
            raise RuntimeError(f"{asset_table} missing ZADDITIONALATTRIBUTES join column")

        if favorites_only and "ZFAVORITE" not in asset_cols:
            raise RuntimeError(f"{asset_table} tidak punya kolom ZFAVORITE")
        if hidden_only and "ZHIDDEN" not in asset_cols:
            raise RuntimeError(f"{asset_table} tidak punya kolom ZHIDDEN")
        if trashed_only and "ZTRASHEDSTATE" not in asset_cols:
            raise RuntimeError(f"{asset_table} tidak punya kolom ZTRASHEDSTATE")

        view_expr_parts = []
        for col in ("ZVIEWCOUNT", "ZPENDINGVIEWCOUNT"):
            if col in add_cols:
                view_expr_parts.append(f"IFNULL(a.{col}, 0)")
        play_expr_parts = []
        for col in ("ZPLAYCOUNT", "ZPENDINGPLAYCOUNT"):
            if col in add_cols:
                play_expr_parts.append(f"IFNULL(a.{col}, 0)")

        album_filter = favorites_only or hidden_only or trashed_only
        if not view_expr_parts and not play_expr_parts and not album_filter:
            raise RuntimeError(
                "Kolom view/play count tidak ada di ZADDITIONALASSETATTRIBUTES. "
                f"Columns: {sorted(add_cols)}"
            )

        views_sql = " + ".join(view_expr_parts) if view_expr_parts else "0"
        plays_sql = " + ".join(play_expr_parts) if play_expr_parts else "0"
        fav_sql = "IFNULL(z.ZFAVORITE, 0)" if "ZFAVORITE" in asset_cols else "0"
        hidden_sql = "IFNULL(z.ZHIDDEN, 0)" if "ZHIDDEN" in asset_cols else "0"
        trashed_sql = "IFNULL(z.ZTRASHEDSTATE, 0)" if "ZTRASHEDSTATE" in asset_cols else "0"

        where = [
            "z.ZFILENAME IS NOT NULL",
            "z.ZDIRECTORY IS NOT NULL",
            f"(({views_sql}) + ({plays_sql})) >= ?",
        ]
        params: list[object] = [min_score]
        if favorites_only:
            where.append(f"({fav_sql}) = 1")
        if hidden_only:
            where.append(f"({hidden_sql}) = 1")
        if trashed_only:
            where.append(f"({trashed_sql}) = 1")
        elif "ZTRASHEDSTATE" in asset_cols:
            # Main / hidden pulls skip Recently Deleted (handled in its own pass).
            where.append(f"({trashed_sql}) = 0")

        sql = f"""
        SELECT
            z.ZDIRECTORY AS directory,
            z.ZFILENAME AS filename,
            ({views_sql}) AS views,
            ({plays_sql}) AS plays,
            ({fav_sql}) AS favorite,
            ({hidden_sql}) AS hidden,
            ({trashed_sql}) AS trashed,
            (({views_sql}) + ({plays_sql})) AS score
        FROM {asset_table} z
        JOIN ZADDITIONALASSETATTRIBUTES a ON a.Z_PK = z.{join_col}
        WHERE {' AND '.join(where)}
        ORDER BY favorite DESC, score DESC, views DESC, plays DESC
        """
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _remote_from_row(directory: str, filename: str) -> str:
    directory = directory.strip("/").replace("\\", "/")
    return f"/{directory}/{filename}"


def _asset_filenames(db_path: Path) -> set[str]:
    """Filenames currently known to Photos.sqlite (any trash/hidden state)."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        asset_table = _pick_asset_table(conn)
        rows = conn.execute(
            f'SELECT ZFILENAME FROM {asset_table} WHERE ZFILENAME IS NOT NULL'
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _carve_jpegs(data: bytes) -> list[bytes]:
    """Best-effort carve of JPEG payloads from Apple .ithmb blobs."""
    out: list[bytes] = []
    i = 0
    while True:
        start = data.find(JPEG_SOI, i)
        if start < 0:
            break
        end = data.find(JPEG_EOI, start + 3)
        if end < 0:
            break
        end += 2
        blob = data[start:end]
        if len(blob) >= 2048:
            out.append(blob)
        i = end
    return out


async def _afc_listdir(afc, path: str) -> list[str]:
    try:
        if not await afc.exists(path):
            return []
        return list(await afc.listdir(path))
    except Exception:
        return []


def _original_from_v2_asset_dir(asset_dir: str) -> str:
    """Map /PhotoData/Thumbnails/V2/<...> back to the likely original AFC path."""
    after_v2 = asset_dir[len(THUMB_V2_ROOT) + 1 :]
    parts = after_v2.split("/")
    if parts and parts[0] == "PhotoData":
        return "/" + "/".join(parts)
    return "/" + "/".join(parts)


async def _collect_v2_thumb_remnants(
    afc,
    known_filenames: set[str],
) -> list[tuple[str, str, str]]:
    """Return (remote_thumb, label, reason) for leftover V2 previews."""
    found: list[tuple[str, str, str]] = []
    for root_name in await _afc_listdir(afc, THUMB_V2_ROOT):
        level1 = f"{THUMB_V2_ROOT}/{root_name}"
        for mid in await _afc_listdir(afc, level1):
            level2 = f"{level1}/{mid}"
            children = await _afc_listdir(afc, level2)
            asset_dirs: list[tuple[str, str]] = []
            for child in children:
                child_path = f"{level2}/{child}"
                if Path(child).suffix:
                    asset_dirs.append((child_path, child))
                else:
                    for nested in await _afc_listdir(afc, child_path):
                        nested_path = f"{child_path}/{nested}"
                        if Path(nested).suffix:
                            asset_dirs.append((nested_path, nested))

            for asset_dir, filename in asset_dirs:
                thumb_name = None
                for candidate in ("5005.JPG", "5005.jpg"):
                    if await afc.exists(f"{asset_dir}/{candidate}"):
                        thumb_name = candidate
                        break
                if thumb_name is None:
                    for ent in await _afc_listdir(afc, asset_dir):
                        if ent.lower().endswith((".jpg", ".jpeg")):
                            thumb_name = ent
                            break
                if not thumb_name:
                    continue

                remote_thumb = f"{asset_dir}/{thumb_name}"
                original_remote = _original_from_v2_asset_dir(asset_dir)
                orig_exists = await afc.exists(original_remote)
                in_db = filename in known_filenames
                if not orig_exists:
                    reason = "missing_original"
                elif not in_db:
                    reason = "unknown_to_db"
                else:
                    continue
                label = f"{reason}__{filename}__{thumb_name}"
                found.append((remote_thumb, label, reason))
    return found


async def _collect_keyframe_remnants(
    afc,
    known_filenames: set[str],
) -> list[tuple[str, str, str]]:
    """Video keyframe JPGs whose source video is gone / unknown to DB."""
    found: list[tuple[str, str, str]] = []
    if not await afc.exists(VIDEO_KEYFRAME_ROOT):
        return found
    for root_name in await _afc_listdir(afc, VIDEO_KEYFRAME_ROOT):
        level1 = f"{VIDEO_KEYFRAME_ROOT}/{root_name}"
        for mid in await _afc_listdir(afc, level1):
            level2 = f"{level1}/{mid}"
            for filename in await _afc_listdir(afc, level2):
                asset_dir = f"{level2}/{filename}"
                keyframe = f"{asset_dir}/LocalVideoKeyFrame.jpg"
                if not await afc.exists(keyframe):
                    continue
                if root_name == "PhotoData":
                    original_remote = f"/PhotoData/{mid}/{filename}"
                else:
                    original_remote = f"/{root_name}/{mid}/{filename}"
                orig_exists = await afc.exists(original_remote)
                in_db = filename in known_filenames
                if not orig_exists:
                    reason = "missing_original"
                elif not in_db:
                    reason = "unknown_to_db"
                else:
                    continue
                label = f"{reason}__{filename}__LocalVideoKeyFrame.jpg"
                found.append((keyframe, label, reason))
    return found


async def _pull_ithmb_carves(afc, out_dir: Path) -> int:
    """Download .ithmb packs and carve embedded JPEG previews."""
    out_dir.mkdir(parents=True, exist_ok=True)
    names = [n for n in await _afc_listdir(afc, THUMB_ITHMB_DIR) if n.lower().endswith(".ithmb")]
    if not names:
        logger.info("Tidak ada file .ithmb untuk di-carve.")
        return 0
    ok = 0
    for name in names:
        remote = f"{THUMB_ITHMB_DIR}/{name}"
        local_pack = out_dir / name
        try:
            await afc.pull(remote, str(local_pack), progress_bar=False)
            data = local_pack.read_bytes()
            jpegs = _carve_jpegs(data)
            logger.info("Carve %s → %d JPEG candidate(s)", name, len(jpegs))
            stem = Path(name).stem
            for i, blob in enumerate(jpegs, 1):
                dest = out_dir / f"{stem}_carve_{i:04d}.jpg"
                dest.write_bytes(blob)
                ok += 1
        except Exception as exc:
            logger.error("  gagal carve %s: %s", name, exc)
    return ok


async def _download_remnant_files(
    afc,
    items: list[tuple[str, str, str]],
    out_dir: Path,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, (remote, label, reason) in enumerate(items, 1):
        local = out_dir / label
        if local.exists():
            local = out_dir / f"{i:03d}_{label}"
        logger.info("[%d/%d] remnant(%s) %s", i, len(items), reason, remote)
        try:
            await afc.pull(remote, str(local), progress_bar=False)
            ok += 1
        except Exception as exc:
            logger.error("  gagal: %s", exc)
    return ok


async def _pull_all_v2_thumb_snapshot(afc, out_dir: Path) -> int:
    """Download every V2/keyframe preview currently on device (low-res cache)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    # V2 previews
    for root_name in await _afc_listdir(afc, THUMB_V2_ROOT):
        level1 = f"{THUMB_V2_ROOT}/{root_name}"
        for mid in await _afc_listdir(afc, level1):
            level2 = f"{level1}/{mid}"
            children = await _afc_listdir(afc, level2)
            asset_dirs: list[tuple[str, str]] = []
            for child in children:
                child_path = f"{level2}/{child}"
                if Path(child).suffix:
                    asset_dirs.append((child_path, child))
                else:
                    for nested in await _afc_listdir(afc, child_path):
                        nested_path = f"{child_path}/{nested}"
                        if Path(nested).suffix:
                            asset_dirs.append((nested_path, nested))
            for asset_dir, filename in asset_dirs:
                thumb_name = None
                for candidate in ("5005.JPG", "5005.jpg"):
                    if await afc.exists(f"{asset_dir}/{candidate}"):
                        thumb_name = candidate
                        break
                if not thumb_name:
                    continue
                remote = f"{asset_dir}/{thumb_name}"
                local = out_dir / f"{filename}__{thumb_name}"
                if local.exists():
                    continue
                try:
                    await afc.pull(remote, str(local), progress_bar=False)
                    ok += 1
                except Exception as exc:
                    logger.debug("skip thumb %s: %s", remote, exc)
    # Video keyframes
    if await afc.exists(VIDEO_KEYFRAME_ROOT):
        for root_name in await _afc_listdir(afc, VIDEO_KEYFRAME_ROOT):
            level1 = f"{VIDEO_KEYFRAME_ROOT}/{root_name}"
            for mid in await _afc_listdir(afc, level1):
                level2 = f"{level1}/{mid}"
                for filename in await _afc_listdir(afc, level2):
                    remote = f"{level2}/{filename}/LocalVideoKeyFrame.jpg"
                    if not await afc.exists(remote):
                        continue
                    local = out_dir / f"{filename}__LocalVideoKeyFrame.jpg"
                    if local.exists():
                        continue
                    try:
                        await afc.pull(remote, str(local), progress_bar=False)
                        ok += 1
                    except Exception as exc:
                        logger.debug("skip keyframe %s: %s", remote, exc)
    return ok


async def _pull_purged_remnants(afc, db_path: Path, out_dir: Path) -> tuple[int, int, int, int]:
    """Best-effort: leftover previews + WAL/tombstone purge metadata.

    Returns (orphan_remnants_ok, thumb_snapshot_ok, ithmb_carve_ok, purge_meta_count).
    """
    from photos_purge_artifacts import (
        correlate_and_restore,
        extract_purge_artifacts,
        write_purge_report,
    )

    remnants_dir = out_dir / "purged_remnants"
    orphan_dir = remnants_dir / "orphans_missing_original"
    snapshot_dir = remnants_dir / "thumb_cache_all"
    ithmb_dir = remnants_dir / "ithmb_carved"
    meta_dir = remnants_dir / "purge_metadata"
    known = _asset_filenames(db_path)

    logger.info("Parse WAL/tombstone untuk jejak file yang sudah di-purge ...")
    try:
        artifacts = extract_purge_artifacts(db_path)
        summary = write_purge_report(artifacts, meta_dir)
        purge_meta_count = int(summary.get("purged_not_in_zasset") or 0)
        named = int(summary.get("purged_with_filename") or 0)
        logger.info(
            "Purge metadata: %d UUID tidak di ZASSET (%d punya filename) → %s",
            purge_meta_count,
            named,
            meta_dir.resolve(),
        )
    except Exception as exc:
        logger.warning("Gagal parse purge artifacts: %s", exc)
        purge_meta_count = 0
        artifacts = []

    logger.info("Scan thumbnail remnant (original hilang / tidak di DB) ...")
    v2 = await _collect_v2_thumb_remnants(afc, known)
    keys = await _collect_keyframe_remnants(afc, known)
    items = v2 + keys
    if items:
        logger.info(
            "Ketemu %d remnant orphan (V2=%d keyframe=%d) → %s",
            len(items),
            len(v2),
            len(keys),
            orphan_dir.resolve(),
        )
        ok_orphan = await _download_remnant_files(afc, items, orphan_dir)
    else:
        logger.info(
            "Tidak ada orphan V2/keyframe (preview ikut terhapus bersama original)."
        )
        ok_orphan = 0

    logger.info("Snapshot semua preview cache V2/keyframe (low-res) ...")
    ok_snap = await _pull_all_v2_thumb_snapshot(afc, snapshot_dir)
    logger.info("Snapshot thumb cache: %d file → %s", ok_snap, snapshot_dir.resolve())

    logger.info("Carve preview dari .ithmb (best-effort; iOS baru sering non-JPEG) ...")
    carved = await _pull_ithmb_carves(afc, ithmb_dir)

    if artifacts:
        logger.info("Tulis jejak hapus (DELETED_KNOWN) + cari salinan lokal ...")
        correlate_and_restore(
            artifacts,
            remnants_dir,
            search_roots=[out_dir.resolve(), Path("output").resolve()],
        )
    return ok_orphan, ok_snap, carved, purge_meta_count


def _rows_to_assets(rows: list[dict], media_type: str) -> list[RankedAsset]:
    assets: list[RankedAsset] = []
    for row in rows:
        filename = row["filename"]
        kind = _classify(filename)
        if kind is None:
            continue
        if media_type == "photo" and kind != "photo":
            continue
        if media_type == "video" and kind != "video":
            continue
        assets.append(
            RankedAsset(
                remote_path=_remote_from_row(row["directory"], filename),
                filename=filename,
                views=int(row["views"] or 0),
                plays=int(row["plays"] or 0),
                favorite=int(row["favorite"] or 0),
                hidden=int(row["hidden"] or 0),
                trashed=int(row["trashed"] or 0),
                kind=kind,
            )
        )
    return assets


def _sort_assets(assets: list[RankedAsset], sort: str) -> list[RankedAsset]:
    if sort == "views":
        assets.sort(key=lambda a: (a.views, a.plays, a.favorite), reverse=True)
    elif sort == "plays":
        assets.sort(key=lambda a: (a.plays, a.views, a.favorite), reverse=True)
    elif sort == "favorites":
        assets.sort(key=lambda a: (a.favorite, a.score, a.views, a.plays), reverse=True)
    else:
        assets.sort(key=lambda a: (a.score, a.favorite, a.views, a.plays), reverse=True)
    return assets


async def _pull_photos_db(afc, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name in PHOTO_DB_FILES:
        remote = f"/PhotoData/{name}"
        if not await afc.exists(remote):
            if name == "Photos.sqlite":
                raise FileNotFoundError("Photos.sqlite tidak ditemukan di /PhotoData")
            continue
        local = dest / name
        logger.info("Ambil %s ...", remote)
        await afc.pull(remote, str(local), progress_bar=False)
        logger.info("  %s (%.1f MB)", local.name, local.stat().st_size / (1024 * 1024))
    return dest / "Photos.sqlite"


def _name_prefix(asset: RankedAsset) -> str:
    parts: list[str] = []
    if asset.favorite:
        parts.append("fav")
    if asset.hidden:
        parts.append("hid")
    if asset.trashed:
        parts.append("del")
    return ("_".join(parts) + "_") if parts else ""


async def _download_assets(afc, assets: list[RankedAsset], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, asset in enumerate(assets, 1):
        tag = _name_prefix(asset)
        local_name = f"{tag}v{asset.views:04d}_p{asset.plays:04d}_{asset.filename}"
        local_path = out_dir / local_name
        if local_path.exists():
            local_path = out_dir / f"{tag}v{asset.views:04d}_p{asset.plays:04d}_{i:03d}_{asset.filename}"

        logger.info(
            "[%d/%d] score=%d (views=%d plays=%d fav=%d hid=%d del=%d) %s",
            i,
            len(assets),
            asset.score,
            asset.views,
            asset.plays,
            asset.favorite,
            asset.hidden,
            asset.trashed,
            asset.remote_path,
        )

        try:
            if not await afc.exists(asset.remote_path):
                logger.warning("  skip: file tidak ada di device (mungkin iCloud-only): %s", asset.remote_path)
                continue
            await afc.pull(asset.remote_path, str(local_path), progress_bar=False)
            ok += 1
        except Exception as exc:
            logger.error("  gagal: %s", exc)
    return ok


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Tarik foto/video sering dilihat/diputar dari Photos.sqlite; "
            "otomatis juga narik Hidden + Recently Deleted + remnant thumbnail."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  .venv/bin/python pull_frequent_media.py
  .venv/bin/python pull_frequent_media.py -n 30
  .venv/bin/python pull_frequent_media.py --min-score 2 -n 50
  .venv/bin/python pull_frequent_media.py --type photo -n 20
  .venv/bin/python pull_frequent_media.py --sort plays -n 20
  .venv/bin/python pull_frequent_media.py --favorites
  .venv/bin/python pull_frequent_media.py --favorites --type photo -n 50

Setiap run otomatis juga mengisi subfolder:
  <output>/hidden/
  <output>/recently_deleted/
  <output>/purged_remnants/   (preview sisa + purge_metadata dari WAL/tombstone)
""",
    )
    p.add_argument("-n", "--count", type=int, default=20, help="Jumlah file teratas (default: 20)")
    p.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="Minimal views+plays untuk ranking utama (default: 1, atau 0 jika --favorites).",
    )
    p.add_argument(
        "--favorites",
        action="store_true",
        help="Hanya media yang di-Favorite (hati) di app Photos (ranking utama).",
    )
    p.add_argument(
        "--sort",
        choices=("total", "views", "plays", "favorites"),
        default="total",
        help="Urutan ranking utama (default: total). 'favorites' = favorit dulu, lalu score.",
    )
    p.add_argument(
        "--type",
        choices=("all", "photo", "video"),
        default="all",
        help="Filter jenis media",
    )
    p.add_argument("-o", "--output", type=Path, default=None, help="Folder output")
    p.add_argument(
        "--keep-db",
        action="store_true",
        help="Simpan salinan Photos.sqlite di output (default: hapus temp)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
    except ImportError:
        logger.error("pymobiledevice3 belum terpasang. Aktifkan .venv dulu.")
        return 2

    if args.count < 1:
        logger.error("--count harus >= 1")
        return 2

    # Favorites often have 0 view-count; default min-score to 0 when filtering favorites.
    min_score = args.min_score
    if min_score is None:
        min_score = 0 if args.favorites else 1
    if min_score < 0:
        logger.error("--min-score harus >= 0")
        return 2

    stamp = time.strftime("%Y%m%d_%H%M%S")
    default_name = f"favorites_{stamp}" if args.favorites else f"frequent_{stamp}"
    out_dir = args.output or Path("output") / default_name
    t0 = time.time()

    tmp = Path(tempfile.mkdtemp(prefix="ios_photos_db_"))
    selected: list[RankedAsset] = []
    hidden_assets: list[RankedAsset] = []
    trashed_assets: list[RankedAsset] = []
    ok_main = ok_hidden = ok_trashed = ok_remnant = ok_snap = ok_ithmb = ok_purge_meta = 0
    try:
        try:
            lockdown = await create_using_usbmux()
        except Exception as exc:
            logger.error("Tidak bisa konek device: %s", exc)
            return 1

        try:
            logger.info(
                "Device: %s | iOS %s | UDID %s",
                lockdown.display_name or lockdown.product_type,
                lockdown.product_version,
                lockdown.udid,
            )
            if args.favorites:
                logger.info("Filter utama: favorites only (ZFAVORITE=1), min-score=%d", min_score)
            logger.info("Otomatis juga tarik: Hidden + Recently Deleted + remnant/cache preview")

            async with AfcService(lockdown) as afc:
                db_path = await _pull_photos_db(afc, tmp)

                if args.keep_db:
                    db_out = out_dir / "photos_db"
                    db_out.mkdir(parents=True, exist_ok=True)
                    for f in tmp.iterdir():
                        shutil.copy2(f, db_out / f.name)
                    logger.info("DB disimpan di %s", db_out)

                # --- Main ranked pull ---
                logger.info("Query ranking utama dari Photos.sqlite ...")
                main_rows = _query_ranked(
                    db_path,
                    min_score=min_score,
                    favorites_only=args.favorites,
                )
                logger.info(
                    "Asset cocok ranking (min-score >= %d%s): %d",
                    min_score,
                    ", favorites" if args.favorites else "",
                    len(main_rows),
                )
                main_assets = _sort_assets(_rows_to_assets(main_rows, args.type), args.sort)
                selected = main_assets[: args.count]

                if selected:
                    logger.info("Top %d ranking (preview):", min(10, len(selected)))
                    for a in selected[:10]:
                        logger.info(
                            "  fav=%d score=%d views=%d plays=%d | %s",
                            a.favorite,
                            a.score,
                            a.views,
                            a.plays,
                            a.filename,
                        )
                    logger.info("Download ranking → %s", out_dir.resolve())
                    ok_main = await _download_assets(afc, selected, out_dir)
                elif args.favorites:
                    logger.warning("Tidak ada media favorit di Photos.sqlite.")
                else:
                    logger.warning(
                        "Tidak ada media dengan view/play count. "
                        "iOS kadang belum menulis count sampai foto dibuka di app Photos."
                    )

                # --- Always pull Hidden ---
                logger.info("Query Hidden album ...")
                try:
                    hidden_rows = _query_ranked(db_path, min_score=0, hidden_only=True)
                except RuntimeError as exc:
                    logger.warning("Hidden tidak tersedia di DB ini: %s", exc)
                    hidden_rows = []
                hidden_assets = _rows_to_assets(hidden_rows, args.type)
                if hidden_assets:
                    hidden_dir = out_dir / "hidden"
                    logger.info("Download Hidden (%d) → %s", len(hidden_assets), hidden_dir.resolve())
                    ok_hidden = await _download_assets(afc, hidden_assets, hidden_dir)
                else:
                    logger.info("Hidden album kosong / tidak ada file cocok filter type.")

                # --- Always pull Recently Deleted ---
                logger.info("Query Recently Deleted ...")
                try:
                    trashed_rows = _query_ranked(db_path, min_score=0, trashed_only=True)
                except RuntimeError as exc:
                    logger.warning("Recently Deleted tidak tersedia di DB ini: %s", exc)
                    trashed_rows = []
                trashed_assets = _rows_to_assets(trashed_rows, args.type)
                if trashed_assets:
                    trashed_dir = out_dir / "recently_deleted"
                    logger.info(
                        "Download Recently Deleted (%d) → %s",
                        len(trashed_assets),
                        trashed_dir.resolve(),
                    )
                    ok_trashed = await _download_assets(afc, trashed_assets, trashed_dir)
                else:
                    logger.info("Recently Deleted kosong / tidak ada file cocok filter type.")

                # --- Best-effort purged remnants (preview + metadata) ---
                ok_remnant, ok_snap, ok_ithmb, ok_purge_meta = await _pull_purged_remnants(
                    afc, db_path, out_dir
                )
        finally:
            # Await async close + drain SSL transport before loop teardown.
            try:
                await lockdown.close()
            except Exception:
                pass
            await asyncio.sleep(0.15)

        elapsed = time.time() - t0
        total_ok = ok_main + ok_hidden + ok_trashed + ok_remnant + ok_snap + ok_ithmb
        logger.info(
            "Selesai: ranking %d/%d | hidden %d/%d | deleted %d/%d | "
            "orphan_preview %d | thumb_cache %d | ithmb_carve %d | "
            "purge_meta %d | pulled %d | %.1fs | %s",
            ok_main,
            len(selected),
            ok_hidden,
            len(hidden_assets),
            ok_trashed,
            len(trashed_assets),
            ok_remnant,
            ok_snap,
            ok_ithmb,
            ok_purge_meta,
            total_ok,
            elapsed,
            out_dir.resolve(),
        )
        return 0 if (total_ok or ok_purge_meta) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_async(coro) -> int:
    """Run coroutine and drain transports before closing the loop.

    pymobiledevice3 SSL sockets otherwise log 'Event loop is closed' on exit.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(coro)
        loop.run_until_complete(asyncio.sleep(0))
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        if pending:
            for t in pending:
                t.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        return result
    finally:
        # Suppress late SSLProtocol callbacks after close.
        def _silence_closed_loop(loop, context):  # noqa: ARG001
            exc = context.get("exception")
            msg = context.get("message", "")
            if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
                return
            if "Fatal error on SSL transport" in msg:
                return
            loop.default_exception_handler(context)

        loop.set_exception_handler(_silence_closed_loop)
        try:
            loop.close()
        except Exception:
            pass
        asyncio.set_event_loop(None)


def main() -> int:
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    return _run_async(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
