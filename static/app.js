/* No CDN, API key, cookie or external service; files stay on localhost. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fileInput = $('fileInput');
  const drop = $('dropzone');
  const selectedSection = $('selectedSection');
  const selectedFiles = $('selectedFiles');
  const startBtn = $('startBtn');
  const uploadStatus = $('uploadStatus');
  const jobsEl = $('jobs');
  const empty = $('emptyState');
  const engineBadge = $('engineBadge');
  let files = [];
  let uploading = false;
  const escapeHtml = v => String(v).replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
  const niceSize = n => n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GB' : n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1024).toFixed(0) + ' KB';
  const stemOrder = ['vocals','instrumental','drums','bass','rhythm','guitar','piano','other'];
  const icons = {vocals:'◉',instrumental:'♫',drums:'⦿',bass:'≋',rhythm:'♬',guitar:'♩',piano:'♮',other:'✦'};

  function showStatus(message, error=false) {
    uploadStatus.textContent = message;
    uploadStatus.classList.toggle('error', error);
  }
  function addFiles(items) {
    const existing = new Set(files.map(f => `${f.name}:${f.size}:${f.lastModified}`));
    let rejected = 0;
    for (const file of Array.from(items || [])) {
      if (file.size <= 0 || file.size > 2 * 1024 ** 3) { rejected++; continue; }
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      if (!existing.has(key)) { files.push(file); existing.add(key); }
    }
    if (rejected) showStatus('কিছু ফাইল খালি বা 2 GB-এর বেশি হওয়ায় যোগ করা হয়নি।', true);
    updateFiles();
  }
  function updateFiles() {
    selectedSection.classList.toggle('hidden', files.length === 0);
    startBtn.disabled = uploading || files.length === 0 || engineBadge.classList.contains('error');
    selectedFiles.innerHTML = files.map((file, i) => `<div class="selected-file"><span class="file-mini-icon">♫</span><span class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span><span class="file-size">${niceSize(file.size)}</span><button class="remove-file" data-remove="${i}" aria-label="Remove file">×</button></div>`).join('');
    selectedFiles.querySelectorAll('button[data-remove]').forEach(btn => btn.addEventListener('click', () => {
      files.splice(Number(btn.dataset.remove), 1); updateFiles();
    }));
  }
  $('browseBtn').addEventListener('click', e => { e.stopPropagation(); fileInput.click(); });
  drop.addEventListener('click', e => { if (e.target !== fileInput && !e.target.closest('button')) fileInput.click(); });
  drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
  fileInput.addEventListener('change', e => { addFiles(e.target.files); fileInput.value = ''; });
  for (const evt of ['dragenter','dragover']) drop.addEventListener(evt, e => { e.preventDefault(); drop.classList.add('dragover'); });
  for (const evt of ['dragleave','drop']) drop.addEventListener(evt, e => { e.preventDefault(); drop.classList.remove('dragover'); });
  drop.addEventListener('drop', e => addFiles(e.dataTransfer.files));
  $('clearBtn').addEventListener('click', () => { files=[]; updateFiles(); showStatus(''); });

  function uploadOne(file, config, number, total) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/jobs?model=${config.model}&format=${config.format}&device=${config.device}`);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.setRequestHeader('X-File-Name', encodeURIComponent(file.name));
      xhr.upload.onprogress = event => {
        if (event.lengthComputable) showStatus(`Uploading ${number}/${total}: ${file.name} • ${Math.round(event.loaded / event.total * 100)}%`);
      };
      xhr.onerror = () => reject(Error('Upload failed. Check the local app is still running.'));
      xhr.onload = () => {
        let response = {};
        try { response = JSON.parse(xhr.responseText); } catch (_) { /* non-JSON error */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(response.job);
        else reject(Error(response.error || `Upload failed: HTTP ${xhr.status}`));
      };
      xhr.send(file);
    });
  }

  startBtn.addEventListener('click', async () => {
    if (uploading || !files.length) return;
    uploading = true; updateFiles();
    const batch = [...files];
    const config = {model: document.querySelector('input[name=model]:checked').value, format: $('format').value, device: $('device').value};
    let successes = 0;
    for (let i = 0; i < batch.length; i++) {
      try {
        await uploadOne(batch[i], config, i+1, batch.length);
        successes++;
        files = files.filter(f => f !== batch[i]);
        await refreshJobs();
      } catch (err) {
        showStatus(`${batch[i].name}: ${err.message}`, true);
      }
    }
    uploading = false; updateFiles();
    if (successes) {
      showStatus(`${successes} file(s) added to the local processing queue. Follow progress below.`);
      $('resultsTitle').scrollIntoView({behavior:'smooth',block:'start'});
    }
  });

  async function checkHealth() {
    try {
      const res = await fetch('/api/health', {cache:'no-store'});
      const data = await res.json();
      const good = data.ffmpeg && data.demucs;
      engineBadge.className = `engine-badge ${good ? 'ready' : 'error'}`;
      engineBadge.textContent = good ? '● ENGINE READY' : '⚠ SETUP REQUIRED';
      engineBadge.title = `Python ${data.python} • FFmpeg: ${data.ffmpeg ? 'installed' : 'missing'} • Demucs: ${data.demucs ? 'installed' : 'missing'}\nOutput: ${data.output_directory}`;
      if (!good) showStatus('Portable AI engine পাওয়া যায়নি। সম্পূর্ণ app ZIP আবার extract করুন।', true);
      updateFiles();
    } catch (_) {
      engineBadge.className = 'engine-badge error';
      engineBadge.textContent = 'OFFLINE / SERVER STOPPED';
      showStatus('App বন্ধ আছে। StemForge Studio চালু করুন।', true);
      updateFiles();
    }
  }

  function renderJob(job) {
    const sig = [job.state, job.stage, job.progress, job.error, job.stems?.length].join('|');
    let node = $('job-' + job.id);
    if (!node) { node = document.createElement('article'); node.id = 'job-' + job.id; node.className = 'job'; jobsEl.appendChild(node); }
    if (node.dataset.sig === sig) return;
    node.dataset.sig = sig;
    const done = job.state === 'done';
    const error = job.state === 'error';
    const name = escapeHtml(job.filename);
    const header = `<div class="job-header"><div><div class="job-title">♫ &nbsp;${name}</div><div class="job-meta">${escapeHtml(job.model)} · ${escapeHtml(job.format.toUpperCase())} · ${escapeHtml(job.created_at?.replace('T',' ').slice(0,19) || '')} UTC</div></div><div class="job-right"><div class="job-status ${done ? 'done' : error ? 'error' : ''}">${done ? '✓ COMPLETE' : error ? '✕ FAILED' : job.state === 'queued' ? '⏳ QUEUED' : '✦ PROCESSING'}</div><div class="job-stage">${escapeHtml(job.stage)}</div></div></div>`;
    let body = '';
    if (error) {
      body = `<div class="job-body"><div class="job-error">${escapeHtml(job.error || 'Could not finish separation. Check FFmpeg, Demucs, free space and model download.')}</div></div>`;
    } else if (!done) {
      body = `<div class="job-body"><div class="progress-track"><div class="progress-fill" style="width:${Math.max(0,Math.min(100,job.progress || 0))}%"></div></div><div class="progress-label">${escapeHtml(job.stage)} • stage ${job.progress || 0}% (approx.)</div></div>`;
    } else {
      const stems = (job.stems || []).slice().sort((a,b)=>stemOrder.indexOf(a.key) - stemOrder.indexOf(b.key));
      const grid = stems.map(s => {
        const url = `/api/file/${encodeURIComponent(job.id)}/${encodeURIComponent(s.key)}`;
        return `<section class="stem-card"><div class="stem-header"><div class="stem-name"><span class="stem-icon">${icons[s.key] || '♪'}</span><span class="stem-title" title="${escapeHtml(s.label)}">${escapeHtml(s.label)}</span></div><span class="stem-size">${niceSize(s.bytes)}</span></div><audio controls preload="none" src="${url}" aria-label="Listen to ${escapeHtml(s.label)}"></audio><div class="stem-actions"><span class="stem-description">${escapeHtml(s.filename)}</span><a class="download-link" href="${url}?download=1">↓ Download</a></div></section>`;
      }).join('');
      body = `<div class="job-body"><div class="stem-grid">${grid}</div><div class="zip-row"><span>✦ ${stems.length} separate audio tracks · Stored on your computer</span><a class="zip-btn" href="/api/zip/${encodeURIComponent(job.id)}">↓ DOWNLOAD ALL · ZIP</a></div></div>`;
    }
    node.innerHTML = header + body;
  }

  async function refreshJobs() {
    try {
      const res = await fetch('/api/jobs', {cache:'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      const jobs = data.jobs || [];
      empty.classList.toggle('hidden', jobs.length > 0);
      const ids = new Set(jobs.map(j => 'job-' + j.id));
      for (const old of Array.from(jobsEl.children)) if (!ids.has(old.id)) old.remove();
      for (const job of jobs) renderJob(job);
      jobs.forEach((job, i) => { const node = $('job-'+job.id); if (node && jobsEl.children[i] !== node) jobsEl.insertBefore(node, jobsEl.children[i] || null); });
    } catch (_) { /* remain usable even while server is busy */ }
  }
  $('closeAppBtn').addEventListener('click', async () => {
    if (!confirm('Close StemForge Studio? Active processing will stop.')) return;
    try {
      await fetch('/api/shutdown', {method:'POST',headers:{'X-StemForge-Request':'close'}});
      showStatus('StemForge Studio is closed. You can close this tab.');
      engineBadge.textContent = 'APP CLOSED';
    } catch (_) { showStatus('Close the app from your system taskbar or dock.'); }
  });
  $('refreshBtn').addEventListener('click', refreshJobs);
  checkHealth(); refreshJobs();
  setInterval(refreshJobs, 1800);
  setInterval(checkHealth, 30000);
})();
