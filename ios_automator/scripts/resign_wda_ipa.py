#!/usr/bin/env python3
"""Resign WebDriverAgent IPA with a local Xcode Apple Development identity."""
from __future__ import annotations

import argparse
import datetime as dt
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def die(msg: str, code: int = 2) -> None:
    print(f"[resign] {msg}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def load_provision(path: Path) -> dict:
    xml = subprocess.check_output(["security", "cms", "-D", "-i", str(path)])
    return plistlib.loads(xml)


def provision_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / "Library/MobileDevice/Provisioning Profiles",
        home / "Library/Developer/Xcode/UserData/Provisioning Profiles",
    ]


def app_id_bundle(entitlements: dict) -> str:
    app_id = str(entitlements.get("application-identifier") or "")
    if "." not in app_id:
        return ""
    return app_id.split(".", 1)[1]


def find_profile(team: str, udid: str, wanted_bundle: str) -> tuple[Path, str]:
    now = dt.datetime.now(dt.timezone.utc)
    wanted = (wanted_bundle or "").strip()
    best: tuple[int, Path, str] | None = None

    for folder in provision_dirs():
        if not folder.is_dir():
            continue
        for path in folder.glob("*.mobileprovision"):
            try:
                data = load_provision(path)
            except (OSError, subprocess.CalledProcessError, plistlib.InvalidFileException):
                continue
            teams = [str(t) for t in (data.get("TeamIdentifier") or [])]
            if team and team not in teams:
                continue
            exp = data.get("ExpirationDate")
            if isinstance(exp, dt.datetime):
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=dt.timezone.utc)
                if exp < now:
                    continue
            devices = [str(d) for d in (data.get("ProvisionedDevices") or [])]
            if udid and devices and udid not in devices:
                continue
            ents = data.get("Entitlements") or {}
            if ents.get("get-task-allow") is not True:
                continue
            bundle = app_id_bundle(ents)
            if not bundle:
                continue
            score = 0
            if bundle == "*":
                score += 8
            if wanted and (bundle == wanted or bundle.rstrip(".*") == wanted):
                score += 20
            if wanted and wanted.startswith(bundle.rstrip("*")):
                score += 6
            if "WebDriverAgent" in bundle or "wda" in bundle.lower():
                score += 12
            if bundle.endswith(".xctrunner"):
                score += 4
            if score == 0:
                continue
            cand = (score, path, bundle if bundle != "*" else wanted)
            if best is None or cand[0] > best[0]:
                best = cand

    if best is None:
        die("Tidak ada provisioning profile development yang cocok (team + device). Xcode akan generate.", 1)
    return best[1], best[2]


def write_entitlements(profile: Path, dest: Path) -> None:
    data = load_provision(profile)
    ents = data.get("Entitlements") or {}
    dest.write_bytes(plistlib.dumps(ents, fmt=plistlib.FMT_XML))


def set_bundle_id(info_plist: Path, bundle_id: str) -> None:
    with info_plist.open("rb") as fh:
        info = plistlib.load(fh)
    info["CFBundleIdentifier"] = bundle_id
    with info_plist.open("wb") as fh:
        plistlib.dump(info, fh)


def iter_sign_targets(app: Path) -> list[Path]:
    """Innermost binaries first, .app last."""
    targets: list[Path] = []
    for pattern in ("*.dylib", "*.framework", "*.appex", "*.xctest"):
        targets.extend(sorted(app.rglob(pattern), key=lambda p: len(p.parts), reverse=True))
    # unique, keep order
    seen: set[Path] = set()
    out: list[Path] = []
    for t in targets:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    out.append(app)
    return out


def codesign(path: Path, identity: str, entitlements: Path | None) -> None:
    cmd = [
        "codesign",
        "--force",
        "--sign",
        identity,
        "--timestamp=none",
        "--generate-entitlement-der",
    ]
    if entitlements is not None:
        cmd.extend(["--entitlements", str(entitlements)])
    cmd.append(str(path))
    run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def sign_ipa(ipa: Path, identity: str, profile: Path, out_ipa: Path, bundle_id: str) -> str:
    if not ipa.is_file():
        die(f"IPA tidak ada: {ipa}")
    work = Path(tempfile.mkdtemp(prefix="wda-resign-"))
    try:
        with zipfile.ZipFile(ipa) as zf:
            zf.extractall(work)
        payload = work / "Payload"
        apps = list(payload.glob("*.app"))
        if not apps:
            die("IPA tidak berisi Payload/*.app")
        app = apps[0]
        for dsym in app.rglob("*.dSYM"):
            shutil.rmtree(dsym, ignore_errors=True)

        info = app / "Info.plist"
        if bundle_id:
            set_bundle_id(info, bundle_id)
            plugin = app / "PlugIns"
            if plugin.is_dir():
                for plist in plugin.rglob("Info.plist"):
                    try:
                        with plist.open("rb") as fh:
                            data = plistlib.load(fh)
                        if str(data.get("CFBundleIdentifier", "")).endswith(".xctest"):
                            data["CFBundleIdentifier"] = f"{bundle_id}.xctest"
                            with plist.open("wb") as fh:
                                plistlib.dump(data, fh)
                    except Exception:
                        pass
        else:
            with info.open("rb") as fh:
                bundle_id = str(plistlib.load(fh).get("CFBundleIdentifier") or "")

        shutil.copy2(profile, app / "embedded.mobileprovision")
        ents = work / "entitlements.plist"
        write_entitlements(profile, ents)

        for target in iter_sign_targets(app):
            use_ents = ents if target == app or target.suffix == ".xctest" else None
            try:
                codesign(target, identity, use_ents)
            except subprocess.CalledProcessError as exc:
                err = (exc.stderr or "").strip()
                die(f"codesign gagal: {target.name}: {err}")

        out_ipa.parent.mkdir(parents=True, exist_ok=True)
        if out_ipa.exists():
            out_ipa.unlink()
        with zipfile.ZipFile(out_ipa, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(payload.rglob("*")):
                if file.is_file():
                    zf.write(file, file.relative_to(work))
        return bundle_id
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_find(args: argparse.Namespace) -> None:
    path, bundle = find_profile(args.team, args.udid, args.bundle or "")
    print(f"{path}\t{bundle}")


def cmd_sign(args: argparse.Namespace) -> None:
    bundle = sign_ipa(
        Path(args.ipa).expanduser().resolve(),
        args.identity,
        Path(args.profile).expanduser().resolve(),
        Path(args.out).expanduser().resolve(),
        args.bundle or "",
    )
    print(bundle)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_find = sub.add_parser("find", help="Cari provisioning profile development yang cocok")
    p_find.add_argument("--team", required=True)
    p_find.add_argument("--udid", required=True)
    p_find.add_argument("--bundle", default="")
    p_find.set_defaults(func=cmd_find)

    p_sign = sub.add_parser("sign", help="Resign IPA")
    p_sign.add_argument("--ipa", required=True)
    p_sign.add_argument("--identity", required=True)
    p_sign.add_argument("--profile", required=True)
    p_sign.add_argument("--out", required=True)
    p_sign.add_argument("--bundle", default="")
    p_sign.set_defaults(func=cmd_sign)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as exc:
        die(str(exc))
