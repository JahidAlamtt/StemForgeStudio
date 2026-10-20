#!/usr/bin/env python3
"""Build the install-free standalone distribution ON THE TARGET OPERATING SYSTEM.

Only builders need Python/FFmpeg dependencies installed in their build runner.
End users launch the resulting application without either installation.
"""
from __future__ import annotations
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    if importlib.util.find_spec('PyInstaller') is None:
        raise SystemExit('Builder setup needed: install requirements-build.txt (only on build system).')
    subprocess.run([sys.executable, str(ROOT/'app.py'), '--self-test'], check=True)
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
            '--onedir', '--name', 'StemForge Studio',
            '--distpath', str(ROOT/'dist'),
            '--workpath', str(ROOT/'build'),
            '--specpath', str(ROOT),
            '--add-data', f'{ROOT/"static"}{os.pathsep}static',
            '--hidden-import=demucs.separate',
            '--hidden-import=imageio_ffmpeg',
            '--hidden-import=torch',
            '--hidden-import=torchaudio']
    if sys.platform in ('darwin', 'win32'):
        args.append('--windowed')
    # Preserve dynamically loaded modules + binary extensions used by the AI model.
    # The FFmpeg executable is packaged as imageio_ffmpeg.binaries package data.
    for mod in ('demucs', 'torch', 'torchaudio', 'imageio_ffmpeg',
                'soundfile', 'julius', 'dora', 'diffq', 'einops',
                'lameenc', 'sphn', 'safetensors', 'openunmix'):
        if importlib.util.find_spec(mod) is not None:
            args.extend(['--collect-all', mod])
    args.append(str(ROOT/'app.py'))
    print('Building a self-contained app for', sys.platform, flush=True)
    subprocess.run(args, cwd=str(ROOT), check=True)
    print('Build complete! Run package_portable.py to make the user download.', flush=True)


if __name__ == '__main__':
    main()
