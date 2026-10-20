"""Unit/integration tests. Fake ONLY the AI network/model call; FFmpeg is real."""
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stemforge_app', ROOT / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class TestStudio(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(app.clean_title('C:\\Music\\My Song.mp3'), 'My Song')
        self.assertEqual(app.clean_title('../../My Track.mov'), 'My Track')
        self.assertEqual(app.clean_title('গান—One.wav'), 'গান_One')

    def test_models_and_formats(self):
        self.assertEqual(len(app.STEMS_4), 4)
        self.assertEqual(len(app.STEMS_6), 6)
        self.assertEqual(app.FORMATS, {'wav', 'mp3', 'flac'})

    def test_self_contained_launch_command(self):
        # Development mode uses local Python; frozen mode calls its own exe.
        from unittest.mock import patch
        with patch.object(app.sys, 'frozen', True, create=True):
            cmd = app.demucs_command('htdemucs', Path('/tmp/out'), Path('/tmp/song.wav'), 'cpu')
            self.assertEqual(cmd[0], app.sys.executable)
            self.assertEqual(cmd[1], '--run-demucs')
            self.assertEqual(cmd[-3:], ['-d', 'cpu', '/tmp/song.wav'])

    def test_bundled_ffmpeg_available(self):
        self.assertTrue(app.ffmpeg_binary())

    def test_http_upload_and_byte_range(self):
        with tempfile.TemporaryDirectory() as td:
            app.JOB_ROOT = Path(td) / 'Exports'
            app.JOB_ROOT.mkdir()
            server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                base = f'http://127.0.0.1:{server.server_address[1]}'
                request = urllib.request.Request(
                    base + '/api/jobs?model=htdemucs&format=wav&device=cpu',
                    data=b'mock_media', method='POST',
                    headers={'X-File-Name': 'My%20Song.mp4',
                             'Content-Type': 'application/octet-stream'},
                )
                result = json.load(urllib.request.urlopen(request))['job']
                jid = result['id']
                self.assertEqual(result['filename'], 'My Song.mp4')
                self.assertEqual((app.JOB_ROOT / jid / 'uploaded_media.mp4').read_bytes(), b'mock_media')
                output = app.JOB_ROOT / jid / 'stems' / 'vocals.wav'
                output.parent.mkdir()
                output.write_bytes(b'ABCDEFGHIJ')
                app.set_job(jid, state='done',
                            stems=[{'key': 'vocals', 'label': 'Vocals', 'filename': 'vocals.wav', 'bytes': 10}])
                request = urllib.request.Request(base + f'/api/file/{jid}/vocals',
                                                  headers={'Range': 'bytes=3-6'})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.read(), b'DEFG')
            finally:
                server.shutdown()
                server.server_close()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg not available')
    def test_pipeline_with_fake_ai(self):
        with tempfile.TemporaryDirectory() as td:
            app.JOB_ROOT = Path(td) / 'Exports'
            app.JOB_ROOT.mkdir()
            wav = Path(td) / 'sine.wav'
            subprocess.run([
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.45',
                '-ac', '2', '-ar', '44100', wav.as_posix(),
            ], check=True)
            orig = app.run_command

            def fake_demucs_or_real(args, job_id, stage):
                if len(args) > 2 and args[1:3] == ['-m', 'demucs']:
                    model = args[args.index('-n') + 1]
                    demucs_root = Path(args[args.index('-o') + 1])
                    path = demucs_root / model / 'source'
                    path.mkdir(parents=True)
                    for stem in (app.STEMS_6 if model == 'htdemucs_6s' else app.STEMS_4):
                        subprocess.run([
                            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                            '-i', args[-1], '-c:a', 'pcm_f32le', str(path / (stem + '.wav')),
                        ], check=True)
                else:
                    orig(args, job_id, stage)

            for model, fmt, stems in [('htdemucs','wav',6), ('htdemucs_6s','mp3',8), ('htdemucs','flac',6)]:
                job_id = uuid.uuid4().hex[:12]
                directory = app.JOB_ROOT / job_id
                directory.mkdir()
                shutil.copy2(wav, directory / 'uploaded_media')
                item = {'id':job_id,'filename':'My Song.mp4','title':'My Song',
                        'model':model,'format':fmt,'device':'cpu',
                        'state':'queued','stage':'Waiting','progress':2,
                        'created_at':app.now(),'finished_at':None,'stems':[],
                        'archive':None,'error':None,'log':[], 'jobdir':str(directory)}
                app.JOBS[job_id] = item
                with patch.object(app, 'run_command', side_effect=fake_demucs_or_real):
                    app.process_job(job_id)
                result = app.JOBS[job_id]
                self.assertEqual(result['state'], 'done', result['error'])
                self.assertEqual(len(result['stems']), stems)
                self.assertTrue((directory / result['archive']).is_file())
                self.assertTrue((directory / 'stems' / f'instrumental.{fmt}').is_file())
                self.assertTrue((directory / 'stems' / f'rhythm.{fmt}').is_file())
                self.assertFalse((directory / 'uploaded_media').exists())
                manifest = json.loads((directory / 'manifest.json').read_text())
                self.assertEqual(manifest['state'], 'done')


if __name__ == '__main__':
    unittest.main()
