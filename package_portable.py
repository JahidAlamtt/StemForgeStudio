#!/usr/bin/env python3
"""Package native PyInstaller app, preserving macOS symlinks and Linux modes."""
from __future__ import annotations
import os
import platform
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
RELEASE = ROOT / 'release'
RELEASE.mkdir(exist_ok=True)
ARCH = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
APP = 'StemForge Studio'


def main():
    if sys.platform == 'darwin':
        src = DIST / f'{APP}.app'
        if not src.exists(): raise SystemExit('macOS .app missing; build failed.')
        out = RELEASE / f'StemForge-Studio-macOS-{ARCH}.zip'
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(src), str(out)], check=True)
        exe = src / 'Contents' / 'MacOS' / APP
    elif sys.platform == 'win32':
        src = DIST / APP
        if not src.exists(): raise SystemExit('Windows portable folder missing; build failed.')
        out = RELEASE / f'StemForge-Studio-Windows-{ARCH}.zip'
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=5, allowZip64=True) as z:
            for p in src.rglob('*'):
                if p.is_file(): z.write(p, p.relative_to(DIST))
        exe = src / f'{APP}.exe'
    else:
        src = DIST / APP
        if not src.exists(): raise SystemExit('Linux portable folder missing; build failed.')
        out = RELEASE / f'StemForge-Studio-Linux-{ARCH}.tar.gz'
        with tarfile.open(out, 'w:gz') as archive:
            archive.add(src, arcname=src.name)
        exe = src / APP
    subprocess.run([str(exe), '--self-test'], check=True)
    print(f'PORTABLE FILE: {out} ({out.stat().st_size / 1048576:.1f} MiB)')


if __name__ == '__main__': main()
