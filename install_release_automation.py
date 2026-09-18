"""Install the complete Lotus release automation 1.1.0 package locally.

Place this file and lotus_release_automation_v1_1_0.zip beside main.py.
Run: python install_release_automation.py
"""

import hashlib
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ARCHIVE = "lotus_release_automation_v1_1_0.zip"
ARCHIVE_SHA = "fcc0f264e3f29cc09f01f7a5f8217f7d919b39b006e6f45b003910cd1272dc7b"
MODULES = (
    "__init__", "commands", "service", "extraction", "public_http",
    "ingestion_store", "ingestion_runner", "ingestion_commands",
)
FILES = ("main.py",) + tuple(f"app/release_catalog/{n}.py" for n in MODULES)
BASE_SHA = {
    "main.py": "cc6104439738d9e4cc9c9010a00575fd5190ba1429eb1da78db04d534b55f2ce",
    "app/release_catalog/__init__.py": "2efde56ba7cdfc66bcea164c78b1d978275c7c6f6f9d17942772d26411b3788c",
    "app/release_catalog/commands.py": "14c109b3532f869999d64ca6275895fffce9751613c4d100f7c911d0702268b6",
    "app/release_catalog/service.py": "b02c3e36ea2c4a9363c4f111192e26db25959ab7c8e80429a0c27f8b0e62c289",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def install():
    if sys.version_info < (3, 11):
        raise SystemExit("Use Python 3.11 or newer.")
    root = Path.cwd().resolve()
    if not (root / "main.py").is_file() or not (root / "app").is_dir():
        raise SystemExit("Run this inside your bot repository, beside main.py.")
    archive = root / ARCHIVE
    if not archive.is_file():
        raise SystemExit(f"Download {ARCHIVE} and place it beside main.py first.")
    package = archive.read_bytes()
    if sha(package) != ARCHIVE_SHA:
        raise SystemExit("ZIP checksum mismatch. Download the original package again.")
    with zipfile.ZipFile(io.BytesIO(package)) as bundle:
        payload = {name: bundle.read(name) for name in FILES}

    originals = {}
    for name, data in payload.items():
        compile(data, name, "exec")  # Syntax check; does not run the bot.
        target = root / name
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise SystemExit(f"Linked destination needs manual review: {name}")
        if target.exists() and not target.is_file():
            raise SystemExit(f"Destination is not a file: {name}")
        old = target.read_bytes() if target.exists() else None
        originals[name] = old
        if old is None or old == data:
            continue
        normalized = old.replace(b"\r\n", b"\n")
        if sha(normalized) not in {BASE_SHA.get(name), sha(data)}:
            raise SystemExit(
                f"{name} has changes outside this package. Nothing was installed.\n"
                "Send that current file for merging so your changes are preserved."
            )
    changed = [name for name in FILES if originals[name] != payload[name]]
    if not changed:
        print("Release automation 1.1.0 is already installed locally.")
        return

    backup = Path(tempfile.mkdtemp(prefix="lotus-release-backup-", dir=root.parent))
    print(f"Backup folder: {backup}", flush=True)
    for name in changed:
        if originals[name] is not None:
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, saved)
    (backup / "NEW_FILES.txt").write_text(
        "".join(name + "\n" for name in changed if originals[name] is None),
        encoding="utf-8",
    )

    with tempfile.TemporaryDirectory(prefix=".lotus-release-stage-", dir=root) as tmp:
        stage = Path(tmp)
        for name in changed:
            staged = stage / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(payload[name])
            if originals[name] is not None:
                shutil.copymode(root / name, staged)
        written = []
        try:
            for name in changed:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                written.append(name)
                os.replace(stage / name, target)
            for name in FILES:
                if (root / name).read_bytes() != payload[name]:
                    raise RuntimeError(f"Installed file verification failed: {name}")
        except BaseException:
            for name in reversed(written):
                if originals[name] is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    shutil.copy2(backup / name, root / name)
            print("Installation failed; affected files restored. Keep the backup.")
            raise

    print("Installed and verified all 9 Python files. No commit or deployment made.")
    print("After you deploy, run /release watch status and check for version 1.1.0.")


if __name__ == "__main__":
    install()
