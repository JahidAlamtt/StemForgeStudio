#!/usr/bin/env python3
"""StemForge Studio Portable: bundled FFmpeg and AI engine. Local only.

Development requires Python dependencies; packaged end users do not install them.
"""
from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

HERE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DATA_ROOT = Path(os.environ.get('STEMFORGE_DATA_DIR', str(Path.home() / 'StemForge Studio'))).expanduser().resolve()
JOB_ROOT = DATA_ROOT / 'Exports'
STATIC = HERE / 'static'
MAX_UPLOAD = 2 * 1024 * 1024 * 1024   # 2 GiB
MODELS = {'htdemucs', 'htdemucs_ft', 'htdemucs_6s'}
FORMATS = {'wav', 'mp3', 'flac'}
STEMS_4 = ('vocals', 'drums', 'bass', 'other')
STEMS_6 = STEMS_4 + ('guitar', 'piano')
STEM_LABELS = {
    'vocals': 'Vocals / Voice',
    'drums': 'Drums / Beat',
    'bass': 'Bass',
    'other': 'Other instruments',
    'guitar': 'Guitar',
    'piano': 'Piano',
    'instrumental': 'Instrumental (no vocals)',
    'rhythm': 'Rhythm (drums + bass)',
}
JOBS: dict[str, dict] = {}
LOCK = threading.RLock()
WORK_QUEUE: queue.Queue[str] = queue.Queue()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def ffmpeg_binary() -> str | None:
    """Find our bundled FFmpeg first, otherwise use the system executable in dev."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).is_file():
            return str(exe)
    except (ImportError, RuntimeError, OSError):
        pass
    return None if getattr(sys, 'frozen', False) else shutil.which('ffmpeg')


def demucs_command(model: str, demucs_dir: Path, source: Path, device: str) -> list[str]:
    """Frozen executable acts as its own Demucs subprocess; avoids needing Python."""
    if getattr(sys, 'frozen', False):
        args = [sys.executable, '--run-demucs']
    else:
        args = [sys.executable, '-m', 'demucs']
    args += ['-n', model, '--float32', '-o', str(demucs_dir)]
    if device == 'cpu':
        args += ['-d', 'cpu']
    return args + [str(source)]


def available() -> dict:
    return {
        'ffmpeg': bool(ffmpeg_binary()),
        'demucs': importlib.util.find_spec('demucs') is not None,
        'python': '.'.join(map(str, sys.version_info[:3])),
        'output_directory': str(JOB_ROOT),
    }


def clean_title(filename: str) -> str:
    """Keep readable international titles while excluding separators and control chars."""
    name = filename.replace('\\', '/').split('/')[-1]
    stem = Path(name).stem
    stem = ''.join(ch if ch.isalnum() or unicodedata.category(ch).startswith('M') or ch in ' .-_' else '_' for ch in stem).strip(' ._-')
    return stem[:80] or 'untitled'


def snapshot(job_id: str) -> dict | None:
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        # Never expose internal filesystem paths or private object references.
        return {k: v for k, v in job.items() if k not in ('jobdir', 'cancelled')}


def persist(job_id: str) -> None:
    with LOCK:
        j = JOBS[job_id]
        jdir = Path(j['jobdir'])
        record = snapshot(job_id)
        tmp = jdir / 'manifest.tmp'
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(jdir / 'manifest.json')


def set_job(job_id: str, **changes) -> None:
    with LOCK:
        JOBS[job_id].update(changes)
        persist(job_id)


def add_log(job_id: str, message: str) -> None:
    msg = str(message).strip()[:450]
    if not msg:
        return
    with LOCK:
        history = JOBS[job_id].setdefault('log', [])
        history.append(msg)
        del history[:-28]
        # Avoid frequent disk writes from noisy tqdm progress.


def check_install() -> None:
    if not ffmpeg_binary():
        raise RuntimeError('Bundled FFmpeg not found. Download the complete portable app and extract all files.')
    if importlib.util.find_spec('demucs') is None:
        raise RuntimeError('AI engine not found. Download the full portable app and extract all files.')


def run_command(args: list[str], job_id: str, stage: str) -> None:
    """No shell=True. Paths are always separate argv entries."""
    if args and args[0] == 'ffmpeg':
        ffmpeg = ffmpeg_binary()
        if not ffmpeg:
            raise RuntimeError('Bundled FFmpeg executable not found')
        args = [ffmpeg, *args[1:]]
    add_log(job_id, f'{stage} started')
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors='replace', bufsize=1,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0),
    )
    assert proc.stdout is not None
    # tqdm sometimes writes carriage-return progress without newlines.
    with proc.stdout:
        for line in proc.stdout:
            # Cap log size, and avoid recording high-frequency progress lines.
            if line.strip() and ('%' not in line or '100%' in line):
                add_log(job_id, line)
    return_code = proc.wait()
    if return_code != 0:
        tail = JOBS[job_id].get('log', [])[-4:]
        raise RuntimeError(f'{stage} failed (exit {return_code}). ' + ' | '.join(tail)[-900:])


def create_mix(job_id: str, wavs: list[Path], out: Path, label: str) -> None:
    missing = [str(p) for p in wavs if not p.is_file()]
    if missing:
        raise RuntimeError(f'Missing {label} sources: {", ".join(missing)}')
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    for stem in wavs:
        args.extend(['-i', str(stem)])
    # The limiter prevents clipping in dense mixes. Its latency compensation
    # keeps the rhythm/instrumental tracks aligned with the exported stems.
    graph = f'amix=inputs={len(wavs)}:duration=first:normalize=0,alimiter=limit=0.98:latency=1'
    args += ['-filter_complex', graph, '-ar', '44100', '-ac', '2', '-c:a', 'pcm_f32le', str(out)]
    run_command(args, job_id, f'Creating {label}')


def convert_format(job_id: str, wav: Path, dest: Path, fmt: str) -> None:
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(wav), '-vn']
    if fmt == 'mp3':
        args += ['-c:a', 'libmp3lame', '-b:a', '320k', str(dest)]
    elif fmt == 'flac':
        args += ['-c:a', 'flac', '-compression_level', '5', str(dest)]
    else:
        args += ['-c:a', 'pcm_s24le', str(dest)]
    run_command(args, job_id, f'Exporting {dest.name}')


def process_job(job_id: str) -> None:
    with LOCK:
        j = JOBS[job_id]
        jobdir = Path(j['jobdir'])
        model, fmt, device = j['model'], j['format'], j['device']
    working = jobdir / '_working'
    working.mkdir(parents=True, exist_ok=True)
    try:
        check_install()
        set_job(job_id, state='processing', stage='Preparing audio from media', progress=8)
        source = working / 'source.wav'
        run_command([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-i', str(jobdir / j.get('input_file', 'uploaded_media')), '-map', '0:a:0', '-vn',
            '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', str(source),
        ], job_id, 'Extracting / converting audio')

        set_job(job_id, stage='AI separation (first run downloads the model)', progress=20)
        demucs_dir = working / 'demucs'
        args = demucs_command(model, demucs_dir, source, device)
        try:
            run_command(args, job_id, 'Demucs source separation')
        except RuntimeError as first_error:
            err = str(first_error).lower()
            if device == 'auto' and ('cuda' in err or 'out of memory' in err or 'mps' in err):
                add_log(job_id, 'Accelerator failed; retrying on CPU.')
                run_command(args[:-1] + ['-d', 'cpu', args[-1]], job_id, 'Demucs CPU fallback')
            else:
                raise

        outwav = demucs_dir / model / 'source'
        names = STEMS_6 if model == 'htdemucs_6s' else STEMS_4
        sources = {name: outwav / f'{name}.wav' for name in names}
        for name, path in sources.items():
            if not path.is_file():
                raise RuntimeError(f'Demucs did not produce expected stem: {name}.wav')

        set_job(job_id, stage='Creating instrumental and rhythm mixes', progress=72)
        instrumental = working / 'instrumental.wav'
        rhythm = working / 'rhythm.wav'
        create_mix(job_id, [sources[k] for k in names if k != 'vocals'], instrumental, 'instrumental')
        create_mix(job_id, [sources['drums'], sources['bass']], rhythm, 'rhythm')
        sources['instrumental'] = instrumental
        sources['rhythm'] = rhythm

        set_job(job_id, stage=f'Exporting {fmt.upper()} audio files', progress=82)
        destination = jobdir / 'stems'
        destination.mkdir(exist_ok=True)
        stems: list[dict] = []
        for index, (name, wav) in enumerate(sources.items()):
            target = destination / f'{name}.{fmt}'
            convert_format(job_id, wav, target, fmt)
            stems.append({'key': name, 'label': STEM_LABELS[name],
                          'filename': target.name, 'bytes': target.stat().st_size})
            set_job(job_id, progress=min(96, 82 + int((index + 1) * 14 / len(sources))))

        set_job(job_id, stage='Packaging all stems into a ZIP', progress=97)
        zip_path = jobdir / f'{clean_title(j["filename"])}_stems.zip'
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_STORED) as zf:
            for stem in stems:
                zf.write(destination / stem['filename'], stem['filename'])
        set_job(job_id, stems=stems, archive=zip_path.name, state='done',
                stage='All stems are ready', progress=100, finished_at=now())
        add_log(job_id, 'All exports completed. The individual files and ZIP are ready.')
        persist(job_id)
    except Exception as exc:
        add_log(job_id, traceback.format_exc().splitlines()[-1])
        set_job(job_id, state='error', stage='Could not process media',
                error=str(exc)[:1100], finished_at=now())
    finally:
        # No large decoded/temporary audio is left behind after each run.
        shutil.rmtree(working, ignore_errors=True)
        try:
            (jobdir / j.get('input_file', 'uploaded_media')).unlink(missing_ok=True)
        except OSError:
            pass


def worker() -> None:
    while True:
        job_id = WORK_QUEUE.get()
        try:
            process_job(job_id)
        except Exception as exc:
            try:
                set_job(job_id, state='error', stage='Unexpected server error', error=str(exc))
            except Exception:
                pass
        finally:
            WORK_QUEUE.task_done()


def restore_existing() -> None:
    if not JOB_ROOT.is_dir():
        return
    for path in JOB_ROOT.glob('*/manifest.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            job_id = str(record.get('id', ''))
            if not re.fullmatch(r'[0-9a-f]{12}', job_id) or job_id != path.parent.name:
                continue
            if record.get('state') in ('processing', 'queued'):
                record.update(state='error', stage='Interrupted',
                              error='The app was closed during processing. Upload again.')
            record['jobdir'] = str(path.parent.resolve())
            with LOCK:
                JOBS[job_id] = record
        except (OSError, ValueError, TypeError):
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'StemForge/1.0'

    def log_message(self, format: str, *args) -> None:
        # Do not print user filenames or paths in server access logs.
        if os.environ.get('STEMFORGE_DEBUG') == '1':
            super().log_message(format, *args)

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_path(self, path: Path, content_type: str, download: bool = False, head: bool = False) -> None:
        if not path.is_file():
            return self.send_json({'error': 'File no longer exists'}, 404)
        size = path.stat().st_size
        start, end, partial = 0, max(0, size - 1), False
        range_value = self.headers.get('Range', '')
        if range_value.startswith('bytes='):
            match = re.fullmatch(r'(\d*)-(\d*)', range_value[6:])
            if match:
                left, right = match.groups()
                if left == '' and right != '':
                    start = max(0, size - int(right))
                else:
                    start = int(left or '0')
                    end = min(size - 1, int(right)) if right else size - 1
                if start >= size or end < start:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.end_headers()
                    return
                partial = True
        length = (end - start + 1) if partial else size
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(path.name))
        self.end_headers()
        if head:
            return
        try:
            with path.open('rb') as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self) -> None:
        self.route_get(head=True)

    def do_GET(self) -> None:
        self.route_get(head=False)

    def route_get(self, head: bool = False) -> None:
        parts = urlsplit(self.path)
        path, params = parts.path, parse_qs(parts.query)
        if path in ('/', '/index.html'):
            return self.send_path(STATIC / 'index.html', 'text/html; charset=utf-8', head=head)
        if path == '/static/app.css':
            return self.send_path(STATIC / 'app.css', 'text/css; charset=utf-8', head=head)
        if path == '/static/app.js':
            return self.send_path(STATIC / 'app.js', 'text/javascript; charset=utf-8', head=head)
        if path == '/api/health':
            return self.send_json(available())
        if path == '/api/jobs':
            with LOCK:
                ids = sorted(JOBS, key=lambda k: JOBS[k]['created_at'], reverse=True)[:60]
            return self.send_json({'jobs': [snapshot(i) for i in ids]})
        match = re.fullmatch(r'/api/jobs/([a-f0-9]{12})', path)
        if match:
            j = snapshot(match.group(1))
            return self.send_json(j) if j else self.send_json({'error': 'Not found'}, 404)
        match = re.fullmatch(r'/api/file/([a-f0-9]{12})/([a-z]+)', path)
        if match:
            job_id, stem = match.groups()
            with LOCK:
                j = JOBS.get(job_id)
                if not j or j.get('state') != 'done':
                    return self.send_json({'error': 'Not ready'}, 404)
                artifact = next((x for x in j['stems'] if x['key'] == stem), None)
                if not artifact:
                    return self.send_json({'error': 'No such stem'}, 404)
                file_path = Path(j['jobdir']) / 'stems' / artifact['filename']
                fmt = j['format']
            content_type = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'flac': 'audio/flac'}[fmt]
            return self.send_path(file_path, content_type, download='1' in params.get('download', []), head=head)
        match = re.fullmatch(r'/api/zip/([a-f0-9]{12})', path)
        if match:
            j = snapshot(match.group(1))
            if not j or j['state'] != 'done':
                return self.send_json({'error': 'Not ready'}, 404)
            file_path = JOB_ROOT / j['id'] / j['archive']
            return self.send_path(file_path, 'application/zip', download=True, head=head)
        self.send_json({'error': 'Not found'}, 404)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == '/api/shutdown':
            # A custom request header rejects cross-site form submissions;
            # browsers cannot send it cross-origin without CORS preflight.
            if self.headers.get('X-StemForge-Request') != 'close':
                return self.send_json({'error': 'Forbidden'}, 403)
            self.send_json({'message': 'StemForge Studio has closed.'})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path != '/api/jobs':
            return self.send_json({'error': 'Not found'}, 404)
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError:
            return self.send_json({'error': 'Invalid upload length'}, 400)
        if not (0 < length <= MAX_UPLOAD):
            return self.send_json({'error': 'File must be between 1 byte and 2 GiB'}, 413)
        opts = parse_qs(urlsplit(self.path).query)
        model = opts.get('model', ['htdemucs'])[0]
        fmt = opts.get('format', ['wav'])[0]
        device = opts.get('device', ['auto'])[0]
        if model not in MODELS or fmt not in FORMATS or device not in ('cpu', 'auto'):
            return self.send_json({'error': 'Invalid model / export format / device'}, 400)
        filename = unquote(self.headers.get('X-File-Name', 'uploaded_media'))[:240]
        filename = filename.replace('\\', '/').split('/')[-1]
        if not filename.strip():
            return self.send_json({'error': 'Missing filename'}, 400)
        if not all(available()[k] for k in ('ffmpeg', 'demucs')):
            return self.send_json({'error': 'The portable audio engine is unavailable. Re-extract the complete app ZIP.'}, 503)
        job_id = uuid.uuid4().hex[:12]
        jobdir = JOB_ROOT / job_id
        # Keep a safe extension to help FFmpeg detect extension-sensitive demuxers.
        suffix = Path(filename).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,12}', suffix):
            suffix = ''
        input_file = 'uploaded_media' + suffix
        jobdir.mkdir(parents=True, exist_ok=False)
        try:
            with (jobdir / input_file).open('wb') as handle:
                pending = length
                while pending:
                    chunk = self.rfile.read(min(1024 * 1024, pending))
                    if not chunk:
                        raise OSError('Upload connection was interrupted')
                    handle.write(chunk)
                    pending -= len(chunk)
            item = {
                'id': job_id, 'filename': filename, 'title': clean_title(filename),
                'input_file': input_file,
                'model': model, 'format': fmt, 'device': device, 'state': 'queued',
                'stage': 'Waiting in local processing queue', 'progress': 2,
                'created_at': now(), 'finished_at': None, 'stems': [],
                'archive': None, 'error': None, 'log': [], 'jobdir': str(jobdir),
            }
            with LOCK:
                JOBS[job_id] = item
                persist(job_id)
            WORK_QUEUE.put(job_id)
            return self.send_json({'job': snapshot(job_id)}, status=201)
        except (OSError, RuntimeError) as exc:
            shutil.rmtree(jobdir, ignore_errors=True)
            return self.send_json({'error': str(exc)}, status=500)


def main() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit('The bundled runtime requires Python 3.10+ (only applicable to developers).')
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    restore_existing()
    threading.Thread(target=worker, daemon=True, name='stemforge-worker').start()
    desired_port = int(os.environ.get('STEMFORGE_PORT', '8765'))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', desired_port), Handler)
    except OSError:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    url = f'http://127.0.0.1:{port}'
    if sys.stdout is not None:
        print(f'\n  StemForge Studio Portable — {url}')
        print(f'  Export folder: {JOB_ROOT}')
        print('  No separate Python or FFmpeg installation is needed for packaged builds.\n')
    if os.environ.get('STEMFORGE_NO_BROWSER') != '1':
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def self_test() -> int:
    """Check portable runtime, packaged static assets and bundled binaries."""
    import importlib
    checks = {'static_assets': all((STATIC / f).is_file() for f in ('index.html', 'app.css', 'app.js')),
              'bundled_ffmpeg': bool(ffmpeg_binary())}
    for mod in ('demucs.separate', 'torch', 'torchaudio', 'imageio_ffmpeg'):
        try:
            importlib.import_module(mod)
            checks[mod] = True
        except Exception as exc:
            checks[mod] = str(exc)
    if sys.stdout is not None:
        print(json.dumps(checks, indent=2))
    return 0 if all(value is True for value in checks.values()) else 1


if __name__ == '__main__':
    # The bundled application uses this entry point in a fresh process to run
    # Demucs, not the user's system Python. Runtime libraries are inside the app.
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        sys.exit(self_test())
    elif len(sys.argv) > 1 and sys.argv[1] == '--run-demucs':
        from demucs.separate import main as demucs_main
        sys.argv = ['demucs', *sys.argv[2:]]
        demucs_main()
    else:
        main()

