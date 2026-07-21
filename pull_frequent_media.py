#!/usr/bin/env python3
"""
Pull frequently viewed/played photos & videos from iOS.

View/play counts live in /PhotoData/Photos.sqlite (not in DCIM file mtime).
This script:
  1) pulls Photos.sqlite (+ WAL/SHM) via AFC
  2) ranks assets by ZVIEWCOUNT / ZPLAYCOUNT (+ pending counts)
  3) downloads matching media files

Device must be unlocked + trusted.
Authorization: Authorized security research / own-device lab use only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sqlite3
import sys
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

PHOTO_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".dng", ".tif", ".tiff", ".gif", ".webp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".3gp"}
PHOTO_DB_FILES = ("Photos.sqlite", "Photos.sqlite-wal", "Photos.sqlite-shm")


@dataclass
class RankedAsset:
    remote_path: str
    filename: str
    views: int
    plays: int
    favorite: int
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

        view_expr_parts = []
        for col in ("ZVIEWCOUNT", "ZPENDINGVIEWCOUNT"):
            if col in add_cols:
                view_expr_parts.append(f"IFNULL(a.{col}, 0)")
        play_expr_parts = []
        for col in ("ZPLAYCOUNT", "ZPENDINGPLAYCOUNT"):
            if col in add_cols:
                play_expr_parts.append(f"IFNULL(a.{col}, 0)")

        if not view_expr_parts and not play_expr_parts and not favorites_only:
            raise RuntimeError(
                "Kolom view/play count tidak ada di ZADDITIONALASSETATTRIBUTES. "
                f"Columns: {sorted(add_cols)}"
            )

        views_sql = " + ".join(view_expr_parts) if view_expr_parts else "0"
        plays_sql = " + ".join(play_expr_parts) if play_expr_parts else "0"
        fav_sql = "IFNULL(z.ZFAVORITE, 0)" if "ZFAVORITE" in asset_cols else "0"

        where = [
            "z.ZFILENAME IS NOT NULL",
            "z.ZDIRECTORY IS NOT NULL",
            f"(({views_sql}) + ({plays_sql})) >= ?",
        ]
        params: list[object] = [min_score]
        if favorites_only:
            where.append(f"({fav_sql}) = 1")

        sql = f"""
        SELECT
            z.ZDIRECTORY AS directory,
            z.ZFILENAME AS filename,
            ({views_sql}) AS views,
            ({plays_sql}) AS plays,
            ({fav_sql}) AS favorite,
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


async def _download_assets(afc, assets: list[RankedAsset], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, asset in enumerate(assets, 1):
        fav_tag = "fav_" if asset.favorite else ""
        local_name = f"{fav_tag}v{asset.views:04d}_p{asset.plays:04d}_{asset.filename}"
        local_path = out_dir / local_name
        if local_path.exists():
            local_path = out_dir / f"{fav_tag}v{asset.views:04d}_p{asset.plays:04d}_{i:03d}_{asset.filename}"

        logger.info(
            "[%d/%d] score=%d (views=%d plays=%d fav=%d) %s",
            i,
            len(assets),
            asset.score,
            asset.views,
            asset.plays,
            asset.favorite,
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
        description="Tarik foto/video yang sering dilihat/diputar (dari Photos.sqlite view/play count).",
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
""",
    )
    p.add_argument("-n", "--count", type=int, default=20, help="Jumlah file teratas (default: 20)")
    p.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="Minimal views+plays (default: 1, atau 0 jika --favorites).",
    )
    p.add_argument(
        "--favorites",
        action="store_true",
        help="Hanya media yang di-Favorite (hati) di app Photos.",
    )
    p.add_argument(
        "--sort",
        choices=("total", "views", "plays", "favorites"),
        default="total",
        help="Urutan ranking (default: total). 'favorites' = favorit dulu, lalu score.",
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

    try:
        lockdown = await create_using_usbmux()
    except Exception as exc:
        logger.error("Tidak bisa konek device: %s", exc)
        return 1

    logger.info(
        "Device: %s | iOS %s | UDID %s",
        lockdown.display_name or lockdown.product_type,
        lockdown.product_version,
        lockdown.udid,
    )
    if args.favorites:
        logger.info("Filter: favorites only (ZFAVORITE=1), min-score=%d", min_score)

    tmp = Path(tempfile.mkdtemp(prefix="ios_photos_db_"))
    try:
        async with AfcService(lockdown) as afc:
            db_path = await _pull_photos_db(afc, tmp)

            logger.info("Query view/play/favorite dari Photos.sqlite ...")
            rows = _query_ranked(
                db_path,
                min_score=min_score,
                favorites_only=args.favorites,
            )
            logger.info(
                "Asset cocok (min-score >= %d%s): %d",
                min_score,
                ", favorites" if args.favorites else "",
                len(rows),
            )

            assets: list[RankedAsset] = []
            for row in rows:
                filename = row["filename"]
                kind = _classify(filename)
                if kind is None:
                    continue
                if args.type == "photo" and kind != "photo":
                    continue
                if args.type == "video" and kind != "video":
                    continue
                assets.append(
                    RankedAsset(
                        remote_path=_remote_from_row(row["directory"], filename),
                        filename=filename,
                        views=int(row["views"] or 0),
                        plays=int(row["plays"] or 0),
                        favorite=int(row["favorite"] or 0),
                        kind=kind,
                    )
                )

            if args.sort == "views":
                assets.sort(key=lambda a: (a.views, a.plays, a.favorite), reverse=True)
            elif args.sort == "plays":
                assets.sort(key=lambda a: (a.plays, a.views, a.favorite), reverse=True)
            elif args.sort == "favorites":
                assets.sort(key=lambda a: (a.favorite, a.score, a.views, a.plays), reverse=True)
            else:
                assets.sort(key=lambda a: (a.score, a.favorite, a.views, a.plays), reverse=True)

            selected = assets[: args.count]
            if not selected:
                if args.favorites:
                    logger.warning("Tidak ada media favorit di Photos.sqlite.")
                else:
                    logger.warning(
                        "Tidak ada media dengan view/play count. "
                        "iOS kadang belum menulis count sampai foto dibuka di app Photos."
                    )
                return 0

            logger.info("Top %d (preview):", min(10, len(selected)))
            for a in selected[:10]:
                logger.info(
                    "  fav=%d score=%d views=%d plays=%d | %s",
                    a.favorite,
                    a.score,
                    a.views,
                    a.plays,
                    a.filename,
                )

            if args.keep_db:
                db_out = out_dir / "photos_db"
                db_out.mkdir(parents=True, exist_ok=True)
                for f in tmp.iterdir():
                    shutil.copy2(f, db_out / f.name)
                logger.info("DB disimpan di %s", db_out)

            logger.info("Download ke %s", out_dir.resolve())
            ok = await _download_assets(afc, selected, out_dir)

        elapsed = time.time() - t0
        logger.info("Selesai: %d/%d file | %.1fs | %s", ok, len(selected), elapsed, out_dir.resolve())
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
