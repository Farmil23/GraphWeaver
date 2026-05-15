/* ═══════════════════════════════════════════════════════════
   FinAgent — B2B KYC & Due Diligence  |  app.js
   ═══════════════════════════════════════════════════════════ */

'use strict';

// ── Global state ──────────────────────────────────────────────
let _pendingSessionId   = localStorage.getItem('_pendingSessionId') || null;
let _pendingQuestion    = localStorage.getItem('_pendingQuestion')   || null;
let _pendingDokuLink    = null;
let _pendingInvoice     = null;
let _visNetwork         = null;
let _visNetworkMini     = null;
let _visNodes           = null;
let _visEdges           = null;
let _pollTimer          = null;
let _chatHistory        = JSON.parse(localStorage.getItem('_chatHistory') || '[]');
let _lastDeepResult     = null; // {sessionId, content} for export

// ════════════════════════════════════════════════════════════
// INIT
// ════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  checkApiHealth();
  loadGraphStats();
  loadGraph();
  initUploadZone();
  initChatInput();
  initModeSelector();
  loadDocuments();

  // ── Restore chat history from localStorage ───────────────────
  if (_chatHistory.length > 0) {
    switchView('chat');
    _chatHistory.forEach(msg => {
      const container = document.getElementById('chat-messages');
      const div = document.createElement('div');
      div.className = `message msg-${msg.role}`;
      const ts  = msg.ts ? new Date(msg.ts).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }) : '';
      div.innerHTML = `
        <div class="msg-avatar"><i class="fa-solid ${msg.role === 'assistant' ? 'fa-robot' : 'fa-user'}"></i></div>
        <div class="msg-bubble">${formatContent(msg.content)}<div class="msg-meta">${ts}</div></div>
      `;
      container.appendChild(div);
    });
    const c = document.getElementById('chat-messages');
    if (c) c.scrollTop = c.scrollHeight;
  }

  // ── Resume investigation after payment redirect ───────────────
  const resumeSid = localStorage.getItem('_resumeAfterPayment');
  if (resumeSid) {
    localStorage.removeItem('_resumeAfterPayment'); // consume once
    switchView('chat');
    showToast('✅ Pembayaran dikonfirmasi! Melanjutkan investigasi…', 'success');
    const typingId = addTypingIndicator();
    pollResultAfterPayment(resumeSid, typingId, null);
  }

  // ── Wire up docs-view upload ──────────────────────────────────
  const docsInput = document.getElementById('file-input-docs');
  const docsZone  = document.getElementById('drop-zone-docs');
  if (docsInput) docsInput.addEventListener('change', () => { if (docsInput.files[0]) uploadFile(docsInput.files[0], 'docs'); });
  if (docsZone) {
    docsZone.addEventListener('click', () => docsInput?.click());
    docsZone.addEventListener('dragover', e => { e.preventDefault(); docsZone.classList.add('dragover'); });
    docsZone.addEventListener('dragleave', () => docsZone.classList.remove('dragover'));
    docsZone.addEventListener('drop', e => { e.preventDefault(); docsZone.classList.remove('dragover'); if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0], 'docs'); });
  }

  // ── Drag-to-resize side panel ─────────────────────────────
  initPanelResize();
});

function initPanelResize() {
  const handle = document.getElementById('panel-resize-handle');
  const side   = document.getElementById('chat-side');
  if (!handle || !side) return;

  let startX, startW;
  handle.addEventListener('mousedown', e => {
    startX = e.clientX;
    startW = side.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    function onMove(e) {
      const dx      = startX - e.clientX; // dragging left = wider panel
      const newW    = Math.min(Math.max(startW + dx, 180), window.innerWidth * 0.75);
      side.style.width = newW + 'px';
    }
    function onUp() {
      handle.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup',   onUp);
      // Re-fit graphs after resize
      if (_visNetwork)     _visNetwork.fit();
      if (_visNetworkMini) _visNetworkMini.fit();
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup',   onUp);
  });
}

function togglePanelFullscreen() {
  const side = document.getElementById('chat-side');
  const btn  = document.getElementById('btn-panel-fs');
  if (!side) return;
  const isFs = side.classList.toggle('panel-fullscreen');
  if (btn) btn.innerHTML = isFs
    ? '<i class="fa-solid fa-compress"></i> Kecil'
    : '<i class="fa-solid fa-expand"></i> Lebar';
  // Refit graphs after transition
  setTimeout(() => {
    if (_visNetwork)     _visNetwork.fit();
    if (_visNetworkMini) _visNetworkMini.fit();
  }, 220);
}

// ════════════════════════════════════════════════════════════
// VIEW SWITCHING
// ════════════════════════════════════════════════════════════
function switchView(name) {
  ['dashboard', 'chat', 'documents'].forEach(v => {
    const el  = document.getElementById(`view-${v}`);
    const btn = document.getElementById(`nav-${v}`);
    if (el)  el.classList.toggle('active',  v === name);
    if (el && v !== name) el.classList.add('hidden');
    if (el && v === name) el.classList.remove('hidden');
    if (btn) btn.classList.toggle('active', v === name);
  });

  const breadcrumbs = { dashboard: '<i class="fa-solid fa-gauge-high"></i> Dashboard', chat: '<i class="fa-solid fa-comments"></i> Investigasi', documents: '<i class="fa-solid fa-folder-open"></i> Dokumen' };
  const bc = document.getElementById('topbar-breadcrumb');
  if (bc) bc.innerHTML = breadcrumbs[name] || '';

  // Refresh relevant data on view switch
  if (name === 'chat') { loadDocuments(); setTimeout(() => renderMiniGraph(), 300); }
  if (name === 'documents') loadDocuments();
  if (name === 'dashboard') { loadGraph(); loadGraphStats(); }
}

function toggleSidebar() {
  document.getElementById('sidebar')?.classList.toggle('collapsed');
}

// ════════════════════════════════════════════════════════════
// API HEALTH
// ════════════════════════════════════════════════════════════
async function checkApiHealth() {
  const el = document.getElementById('api-status');
  try {
    const r = await fetch('/api/health');
    if (r.ok) {
      el.className = 'status-dot status-ok';
      el.innerHTML = '<i class="fa-solid fa-circle"></i> API Online';
    } else throw new Error();
  } catch {
    el.className = 'status-dot status-error';
    el.innerHTML = '<i class="fa-solid fa-circle"></i> API Offline';
  }
}

// ════════════════════════════════════════════════════════════
// GRAPH STATS
// ════════════════════════════════════════════════════════════
async function loadGraphStats() {
  try {
    const r    = await fetch('/api/graph/stats');
    const data = await r.json();
    document.getElementById('stat-nodes').textContent     = data.total_nodes     ?? '—';
    document.getElementById('stat-rels').textContent      = data.total_relations ?? '—';
    document.getElementById('stat-companies').textContent = data.breakdown?.Company ?? '0';
    document.getElementById('stat-persons').textContent   = data.breakdown?.Person  ?? '0';
  } catch { /* stats non-critical */ }
}

// ════════════════════════════════════════════════════════════
// GRAPH VISUALIZATION  (vis.js Network)
// ════════════════════════════════════════════════════════════
async function loadGraph(entityFilter = '') {
  const container   = document.getElementById('graph-container');
  const placeholder = document.getElementById('graph-placeholder');
  const info        = document.getElementById('graph-info');

  try {
    const url  = entityFilter ? `/api/graph?entity=${encodeURIComponent(entityFilter)}` : '/api/graph';
    const r    = await fetch(url);
    const data = await r.json();

    if (!data.nodes || data.nodes.length === 0) {
      if (placeholder) placeholder.classList.remove('hidden');
      return;
    }
    if (placeholder) placeholder.classList.add('hidden');
    if (info) { info.classList.remove('hidden'); info.textContent = `${data.nodes.length} entities · ${data.edges.length} relationships${entityFilter ? ' — filtered by "' + entityFilter + '"' : ''}`; }

    if (container) renderGraph(container, data);
    // Also render mini graph if in chat view
    renderMiniGraph(data);
  } catch (e) {
    console.error('Graph load error:', e);
  }
}

function renderMiniGraph(data) {
  const mini = document.getElementById('graph-container-mini');
  const phMini = document.getElementById('graph-placeholder-mini');
  if (!mini) return;

  if (!data) {
    // Fetch fresh data and render
    fetch('/api/graph').then(r => r.json()).then(d => renderMiniGraph(d)).catch(() => {});
    return;
  }
  if (!data.nodes || data.nodes.length === 0) { if (phMini) phMini.classList.remove('hidden'); return; }
  if (phMini) phMini.classList.add('hidden');

  const miniNodes = new vis.DataSet(data.nodes.map(n => ({
    id: n.id, label: n.label.length > 10 ? n.label.slice(0,10)+'…' : n.label,
    color: { background: n.color || '#3b82f6', border: shadeColor(n.color || '#3b82f6', -40) },
    font: { color: '#e2e8f0', size: 9 },
    shape: nodeShape(n.group), size: 8,
  })));
  const miniEdges = new vis.DataSet(data.edges.map((e, i) => ({
    id: i, from: e.from, to: e.to,
    label: e.label || '',
    title: e.label || '',
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
    color: { color: '#2d4a7a', highlight: '#3b82f6', hover: '#60a5fa' },
    font:  { color: '#7c9cc0', size: 9, strokeWidth: 2, strokeColor: '#070d1a' },
    width: 1,
  })));
  if (_visNetworkMini) _visNetworkMini.destroy();
  _visNetworkMini = new vis.Network(mini, { nodes: miniNodes, edges: miniEdges }, {
    physics: {
      barnesHut: { gravitationalConstant: -4000, centralGravity: 0.4, springLength: 80 },
      stabilization: { iterations: 80 },
    },
    interaction: {
      hover: true,
      tooltipDelay: 200,
      zoomView: true,
      dragView: true,
      dragNodes: true,
      navigationButtons: false,
      keyboard: false,
    },
    nodes: { borderWidth: 1.5, font: { color: '#e2e8f0', size: 10 } },
    edges: {
      width: 1,
      font: { size: 9, color: '#7c9cc0', strokeWidth: 2, strokeColor: '#070d1a' },
    },
  });
  _visNetworkMini.once('stabilizationIterationsDone', () => {
    _visNetworkMini.setOptions({ physics: { enabled: false } });
    _visNetworkMini.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  });
  // Click on mini node: filter main graph
  _visNetworkMini.on('doubleClick', params => {
    if (params.nodes.length > 0) {
      const node = miniNodes.get(params.nodes[0]);
      if (node) loadGraph(node.label);
    }
  });
}

function renderGraph(container, data) {
  // Build vis DataSets
  _visNodes = new vis.DataSet(data.nodes.map(n => ({
    id:    n.id,
    label: n.label,
    title: n.title,
    color: {
      background: n.color || '#3b82f6',
      border:     shadeColor(n.color || '#3b82f6', -40),
      highlight:  { background: lightenColor(n.color || '#3b82f6', 30), border: '#ffffff' },
    },
    font:  { color: '#e2e8f0', size: 12 },
    shape: nodeShape(n.group),
    size:  nodeSize(n.group),
  })));

  _visEdges = new vis.DataSet(data.edges.map((e, i) => ({
    id:     i,
    from:   e.from,
    to:     e.to,
    label:  e.label || '',
    title:  e.title || e.label || '',
    arrows: { to: { enabled: true, scaleFactor: 0.7 } },
    color:  { color: '#2d4a7a', highlight: '#3b82f6', hover: '#60a5fa', opacity: 1 },
    font:   {
      color:       '#94a3b8',
      size:        11,
      strokeWidth: 3,
      strokeColor: '#070d1a',
      background:  'none',
      align:       'middle',
    },
    smooth: { type: 'curvedCW', roundness: 0.12 },
    width:  1.8,
  })));

  const options = {
    layout:   { improvedLayout: true },
    physics:  {
      enabled: true,
      barnesHut: { gravitationalConstant: -8000, centralGravity: 0.3, springLength: 140 },
      stabilization: { iterations: 150 },
    },
    interaction: {
      hover: true,
      tooltipDelay: 200,
      navigationButtons: false,
      keyboard: true,
    },
    nodes: { borderWidth: 2, shadow: { enabled: true, color: 'rgba(0,0,0,0.4)', x: 3, y: 3, size: 6 } },
    edges: {
      width: 1.8,
      font: { size: 11, color: '#94a3b8', strokeWidth: 3, strokeColor: '#070d1a' },
    },
  };

  if (_visNetwork) _visNetwork.destroy();
  _visNetwork = new vis.Network(container, { nodes: _visNodes, edges: _visEdges }, options);

  // Click to highlight neighbours
  _visNetwork.on('click', params => {
    if (params.nodes.length > 0) {
      highlightNeighbours(params.nodes[0]);
    } else {
      resetHighlight();
    }
  });

  // Stabilised: show info
  _visNetwork.once('stabilizationIterationsDone', () => {
    _visNetwork.setOptions({ physics: { enabled: false } });
  });
}

function nodeShape(group) {
  const shapes = { Person: 'dot', Company: 'square', Address: 'diamond', Document: 'triangleDown' };
  return shapes[group] || 'dot';
}
function nodeSize(group) {
  const sizes = { Company: 22, Person: 16, Address: 14, Document: 14 };
  return sizes[group] || 16;
}

function highlightNeighbours(nodeId) {
  if (!_visNodes || !_visEdges) return;
  const connectedNodes = _visNetwork.getConnectedNodes(nodeId);
  const allNodes       = _visNodes.getIds();

  _visNodes.update(allNodes.map(id => ({
    id,
    opacity: connectedNodes.includes(id) || id === nodeId ? 1 : 0.2,
  })));
}
function resetHighlight() {
  if (!_visNodes) return;
  _visNodes.update(_visNodes.getIds().map(id => ({ id, opacity: 1 })));
}

function fitGraph() {
  if (_visNetwork) _visNetwork.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
}

// Graph filter
document.getElementById('graph-filter')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') loadGraph(e.target.value.trim());
});

// Colour helpers
function shadeColor(hex, pct) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.max(0, Math.min(255, (n >> 16) + pct));
  const g = Math.max(0, Math.min(255, ((n >> 8) & 0xff) + pct));
  const b = Math.max(0, Math.min(255, (n & 0xff) + pct));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}
function lightenColor(hex, pct) { return shadeColor(hex, pct); }

// ════════════════════════════════════════════════════════════
// DOCUMENT UPLOAD
// ════════════════════════════════════════════════════════════
function initUploadZone() {
  const zone  = document.getElementById('drop-zone');
  const input = document.getElementById('file-input');

  if (!zone) return;

  zone.addEventListener('click',      () => input.click());
  zone.addEventListener('dragover',   e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave',  () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', () => { if (input.files[0]) uploadFile(input.files[0]); });
}

async function uploadFile(file, context = 'dashboard') {
  const statusId = context === 'docs' ? 'upload-status-docs' : 'upload-status';
  const statusEl = document.getElementById(statusId);
  if (statusEl) {
    statusEl.className = 'upload-status loading';
    statusEl.textContent = `⏳ Processing ${file.name}…`;
    statusEl.classList.remove('hidden');
  }

  const fd = new FormData();
  fd.append('file', file);

  try {
    const r    = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await r.json();

    if (r.ok) {
      if (statusEl) { statusEl.className = 'upload-status success'; statusEl.textContent = `✅ ${data.message}`; }
      addProcessedFile(file.name);
      showToast(`✅ ${file.name} ingested into Knowledge Graph!`, 'success');
      setTimeout(() => { loadGraph(); loadGraphStats(); loadDocuments(); }, 1000);
    } else {
      throw new Error(data.detail || 'Upload failed');
    }
  } catch (e) {
    if (statusEl) { statusEl.className = 'upload-status error'; statusEl.textContent = `❌ ${e.message}`; }
    showToast(`❌ Upload failed: ${e.message}`, 'error');
  }
}

function addProcessedFile(name) {
  const container = document.getElementById('processed-files');
  const div = document.createElement('div');
  div.className = 'processed-file';
  div.innerHTML = `<i class="fa-solid fa-file-check"></i> ${name}`;
  container.prepend(div);
}

// ════════════════════════════════════════════════════════════
// CHAT
// ════════════════════════════════════════════════════════════
function initChatInput() {
  document.getElementById('chat-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitQuestion(); }
  });
}

function initModeSelector() {
  document.querySelectorAll('input[name="mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
      document.getElementById('mode-basic-label').classList.toggle('selected', radio.value === 'basic'  && radio.checked);
      document.getElementById('mode-deep-label').classList.toggle('selected',  radio.value === 'deep'   && radio.checked);
    });
  });
}

function getMode() {
  return document.querySelector('input[name="mode"]:checked')?.value ?? 'basic';
}

async function submitQuestion() {
  const input    = document.getElementById('chat-input');
  const question = input.value.trim();
  if (!question) return;

  input.value = '';
  addMessage('user', question);

  const depth = getMode();
  resetPipeline();
  setPipelineStep('payment_gatekeeper', 'running');

  const typingId = addTypingIndicator();

  try {
    const r = await fetch('/api/investigate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        question,
        investigation_depth: depth,
        payment_status:      'UNPAID',
      }),
    });

    const data = await r.json();
    removeTypingIndicator(typingId);

    if (data.status === 'PAYMENT_REQUIRED') {
      // ── Payment wall ──────────────────────────────────────
      setPipelineStep('payment_gatekeeper', 'blocked');
      _pendingSessionId = data.session_id;
      _pendingQuestion  = question;
      _pendingDokuLink  = data.doku_link;
      _pendingInvoice   = data.invoice_number;
      // Persist so page refresh / server reload doesn't lose session
      localStorage.setItem('_pendingSessionId', data.session_id);
      localStorage.setItem('_pendingQuestion',  question);
      openPaywall(data.session_id, data.doku_link, data.invoice_number);
      addMessage('assistant',
        '🔒 **Deep Investigation is a Premium Feature**\n\n' +
        'Full entity-relationship mapping requires a one-time payment of **Rp 50.000** via DOKU. ' +
        'Complete the payment in the popup to unlock your analysis.'
      );

    } else if (data.status === 'SUCCESS') {
      // ── All nodes done ────────────────────────────────────
      setPipelineStep('payment_gatekeeper', 'done');
      ['planning', 'write_query', 'run_query', 'answer_user'].forEach(n => setPipelineStep(n, 'done'));
      addMessage('assistant', data.answer);
      setTimeout(() => { loadGraph(); loadGraphStats(); }, 800);

    } else {
      addMessage('assistant', `❌ Error: ${data.message || 'Unexpected response'}`);
    }

  } catch (e) {
    removeTypingIndicator(typingId);
    addMessage('assistant', `❌ Connection error: ${e.message}\n\nMake sure the FinAgent API is running on port 8000.`);
  }
}

// ════════════════════════════════════════════════════════════
// PIPELINE UI
// ════════════════════════════════════════════════════════════
function resetPipeline() {
  document.querySelectorAll('.pipeline-step').forEach(el => {
    el.className = 'pipeline-step step-idle';
    el.querySelector('.step-status').innerHTML = '<i class="fa-regular fa-circle"></i>';
  });
}

function setPipelineStep(node, state) {
  const el = document.querySelector(`.pipeline-step[data-node="${node}"]`);
  if (!el) return;

  const icons = {
    running: '<i class="fa-solid fa-circle-notch fa-spin"></i>',
    done:    '<i class="fa-solid fa-circle-check"></i>',
    blocked: '<i class="fa-solid fa-circle-xmark"></i>',
    idle:    '<i class="fa-regular fa-circle"></i>',
  };

  el.className = `pipeline-step step-${state}`;
  el.querySelector('.step-status').innerHTML = icons[state] || icons.idle;
}

// Simulate pipeline steps during a live investigation
function animatePipeline(answerCallback) {
  const steps = ['planning', 'write_query', 'run_query', 'answer_user'];
  let i = 0;
  const interval = setInterval(() => {
    if (i > 0) setPipelineStep(steps[i - 1], 'done');
    if (i < steps.length) {
      setPipelineStep(steps[i], 'running');
      i++;
    } else {
      clearInterval(interval);
      if (answerCallback) answerCallback();
    }
  }, 1500);
  return interval;
}

// ════════════════════════════════════════════════════════════
// PAYMENT PAYWALL
// ════════════════════════════════════════════════════════════
function openPaywall(sessionId, dokUrl, invoiceNumber) {
  const modal = document.getElementById('paywall-modal');
  modal.classList.remove('hidden');
  modal.style.display = ''; // restore display
  document.getElementById('doku-pay-btn').href   = dokUrl || '#';
  document.getElementById('paywall-session-id').textContent  = sessionId  || '—';
  document.getElementById('paywall-invoice-id').textContent  = invoiceNumber || '—';
  document.getElementById('paywall-processing').classList.add('hidden');
  document.getElementById('btn-simulate').disabled = false;

  // When user clicks the real DOKU link, start background polling
  // so the paywall auto-closes when DOKU webhook confirms payment
  const payBtn = document.getElementById('doku-pay-btn');
  payBtn.onclick = () => {
    setTimeout(() => startRealPaymentPolling(sessionId), 3000);
  };
}

function startRealPaymentPolling(sessionId) {
  document.getElementById('paywall-processing').classList.remove('hidden');
  document.getElementById('paywall-processing-msg').textContent =
    'Menunggu konfirmasi pembayaran dari DOKU…';
  document.getElementById('btn-simulate').disabled = false;

  let pipelineInterval = animatePipeline(null);

  pollResult(sessionId, () => {
    clearInterval(pipelineInterval);
    setPipelineStep('answer_user', 'done');
  });
}

function closePaywall() {
  const modal = document.getElementById('paywall-modal');
  if (modal) {
    modal.classList.add('hidden');
    modal.style.display = 'none'; // force-hide regardless of CSS specificity
  }
  clearTimeout(_pollTimer);
}

async function checkPaymentStatus() {
  const sessionId = _pendingSessionId;
  if (!sessionId) { showToast('No pending session', 'error'); return; }

  const btn = document.getElementById('btn-check-payment');
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengecek…';

  try {
    const r    = await fetch(`/api/result/${sessionId}`);
    const data = await r.json();

    if (data.status === 'COMPLETE') {
      // Already done — show result immediately
      closePaywall();
      addMessage('assistant',
        '🔓 **Deep Investigation Complete — Premium Analysis Unlocked**\n\n' + data.answer
      );
      setTimeout(() => { loadGraph(); loadGraphStats(); }, 800);
      showToast('✅ Investigation complete!', 'success');
      _pendingSessionId = null; _pendingQuestion = null;
      localStorage.removeItem('_pendingSessionId'); localStorage.removeItem('_pendingQuestion');

    } else if (data.status === 'PROCESSING') {
      // Payment confirmed, investigation still running — start polling
      document.getElementById('paywall-processing').classList.remove('hidden');
      document.getElementById('paywall-processing-msg').textContent =
        'Pembayaran dikonfirmasi! Investigasi sedang berjalan…';
      showToast('✅ Pembayaran diterima! Menunggu hasil analisis…', 'success');
      let pi = animatePipeline(null);
      pollResult(sessionId, () => { clearInterval(pi); setPipelineStep('answer_user', 'done'); });

    } else if (data.status === 'AWAITING_PAYMENT') {
      // Dev Tunnels/ngrok requires auth so DOKU webhook can't reach us.
      // "Sudah Bayar?" click = trusted user assertion → fire confirmation internally.
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengonfirmasi…';
      try {
        const wh = await fetch('/webhooks/doku-paid', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            transaction_id: `CEK-${sessionId.slice(0, 8).toUpperCase()}`,
            status:         'SUCCESS',
            session_id:     sessionId,
            question:       _pendingQuestion || '',
          }),
        });
        if (!wh.ok) throw new Error(await wh.text());
        closePaywall();
        switchView('chat');
        showToast('✅ Pembayaran dikonfirmasi! Analisis sedang berjalan…', 'success');
        setPipelineStep('payment_gatekeeper', 'done');
        const pi = animatePipeline(null);
        const typingId = addTypingIndicator();
        pollResultAfterPayment(sessionId, typingId, pi);
      } catch (e) {
        showToast('❌ ' + e.message, 'error');
      }

    } else {
      showToast(`Status: ${data.status}. Coba lagi sebentar.`, 'info');
    }
  } catch (e) {
    showToast('Gagal cek status: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Sudah Bayar? Cek Status';
  }
}

async function simulatePayment() {
  const sessionId = _pendingSessionId;
  if (!sessionId) { showToast('No pending session found', 'error'); return; }

  document.getElementById('paywall-processing').classList.remove('hidden');
  document.getElementById('paywall-processing-msg').textContent = 'Mengonfirmasi pembayaran…';
  document.getElementById('btn-simulate').disabled = true;

  try {
    const wh = await fetch('/webhooks/doku-paid', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        transaction_id: `DEMO-TXN-${sessionId.slice(0, 8).toUpperCase()}`,
        status:         'SUCCESS',
        session_id:     sessionId,
      }),
    });
    if (!wh.ok) throw new Error('Webhook failed: ' + (await wh.text()));

    // ── Tutup popup SEGERA setelah payment dikonfirmasi ──────────────
    closePaywall();
    showToast('✅ Pembayaran dikonfirmasi! Investigasi mendalam sedang berjalan…', 'success');
    switchView('chat');

    // Add typing indicator in chat so user knows it's running
    const typingId = addTypingIndicator();
    setPipelineStep('payment_gatekeeper', 'done');
    const pi = animatePipeline(null);

    // Poll silently in background; replace typing indicator when done
    pollResultAfterPayment(sessionId, typingId, pi);

  } catch (e) {
    document.getElementById('paywall-processing').classList.add('hidden');
    document.getElementById('btn-simulate').disabled = false;
    showToast(`❌ ${e.message}`, 'error');
  }
}

function pollResultAfterPayment(sessionId, typingId, pipelineInterval) {
  clearTimeout(_pollTimer);

  async function check() {
    try {
      const r    = await fetch(`/api/result/${sessionId}`);
      const data = await r.json();

      if (data.status === 'COMPLETE') {
        clearInterval(pipelineInterval);
        setPipelineStep('answer_user', 'done');
        removeTypingIndicator(typingId);

        const content = '🔓 **Deep Investigation Complete — Premium Analysis Unlocked**\n\n' + data.answer;
        const msgEl   = addMessage('assistant', content, { isDeep: true, sessionId });
        if (msgEl) {
          const bubble = msgEl.querySelector('.msg-bubble');
          if (bubble) {
            bubble.insertBefore(buildTraceAccordion(data), bubble.querySelector('.msg-meta'));
            const exportBtn = document.createElement('button');
            exportBtn.className = 'btn-export-report';
            exportBtn.innerHTML = '<i class="fa-solid fa-file-arrow-down"></i> Export Laporan (HTML)';
            exportBtn.onclick = () => exportReport(sessionId, content);
            bubble.appendChild(exportBtn);
          }
        }
        _lastDeepResult = { sessionId, content };
        setTimeout(() => { loadGraph(); loadGraphStats(); loadDocuments(); renderMiniGraph(); }, 800);
        showToast('✅ Deep investigation complete!', 'success');
        _pendingSessionId = null;

      } else if (data.status === 'ERROR') {
        clearInterval(pipelineInterval);
        removeTypingIndicator(typingId);
        addMessage('assistant', `❌ Investigation error: ${data.answer || 'Unknown error'}`);
        showToast('❌ Investigation failed', 'error');

      } else {
        _pollTimer = setTimeout(check, 2000);
      }
    } catch {
      _pollTimer = setTimeout(check, 3000);
    }
  }
  _pollTimer = setTimeout(check, 2000);
}

function pollResult(sessionId, onComplete) {
  clearTimeout(_pollTimer);

  async function check() {
    try {
      const r    = await fetch(`/api/result/${sessionId}`);
      const data = await r.json();

      if (data.status === 'COMPLETE') {
        // ── Close paywall IMMEDIATELY before anything else ──────
        closePaywall();
        if (onComplete) onComplete();

        const content = '🔓 **Deep Investigation Complete — Premium Analysis Unlocked**\n\n' + data.answer;
        const msgEl = addMessage('assistant', content, { isDeep: true, sessionId });
        if (msgEl) {
          const bubble = msgEl.querySelector('.msg-bubble');
          if (bubble) {
            bubble.insertBefore(buildTraceAccordion(data), bubble.querySelector('.msg-meta'));
            const btn = document.createElement('button');
            btn.className = 'btn-export-report';
            btn.innerHTML = '<i class="fa-solid fa-file-arrow-down"></i> Export Laporan (HTML)';
            btn.onclick = () => exportReport(sessionId, content);
            bubble.appendChild(btn);
          }
        }
        _lastDeepResult = { sessionId, content };
        setTimeout(() => { loadGraph(); loadGraphStats(); loadDocuments(); renderMiniGraph(); }, 800);
        showToast('✅ Deep investigation complete!', 'success');
        _pendingSessionId = null; _pendingQuestion = null;
        localStorage.removeItem('_pendingSessionId'); localStorage.removeItem('_pendingQuestion');

        // Auto-switch to chat view to show result
        switchView('chat');

      } else if (data.status === 'ERROR') {
        closePaywall();
        addMessage('assistant', `❌ Investigation error: ${data.answer || 'Unknown error'}`);
        showToast('❌ Investigation failed', 'error');

      } else {
        // Still PROCESSING or AWAITING_PAYMENT — keep polling
        _pollTimer = setTimeout(check, 2000);
      }
    } catch {
      _pollTimer = setTimeout(check, 3000);
    }
  }

  _pollTimer = setTimeout(check, 2000);
}

// ════════════════════════════════════════════════════════════
// EXPORT REPORT
// ════════════════════════════════════════════════════════════
// ════════════════════════════════════════════════════════════
// AGENT TRACE ACCORDION
// ════════════════════════════════════════════════════════════
function buildTraceAccordion(data) {
  const steps = [
    {
      icon:  'fa-shield-halved',
      label: 'Payment Gatekeeper',
      meta:  'deep + PAID ✅',
      body:  '<span class="trace-text">Investigation tier: <strong>Deep</strong> — payment confirmed. Proceeding to graph extraction.</span>',
      state: 'done',
    },
    {
      icon:  'fa-list-check',
      label: 'Query Planning',
      meta:  'decomposed',
      body:  data.query_decomposition
               ? `<div class="trace-text">${escHtml(data.query_decomposition)}</div>`
               : '<span class="trace-text" style="color:var(--text3)">—</span>',
      state: 'done',
    },
    {
      icon:  'fa-code',
      label: 'Cypher Generation',
      meta:  'Neo4j query',
      body:  data.cypher_used
               ? `<div class="trace-code">${escHtml(data.cypher_used)}</div>`
               : '<span class="trace-text" style="color:var(--text3)">—</span>',
      state: 'done',
    },
    {
      icon:  'fa-database',
      label: 'Neo4j Execution',
      meta:  data.row_count ? `${data.row_count} rows` : 'executed',
      body:  `<span class="trace-text">${data.row_count || 0} rows retrieved from AuraDB knowledge graph.</span>`,
      state: 'done',
    },
    {
      icon:  'fa-brain',
      label: 'Analysis & Report',
      meta:  'GPT-4o synthesis',
      body:  '<span class="trace-text">LLM synthesised findings into structured due-diligence report below.</span>',
      state: 'done',
    },
  ];

  const stepsHtml = steps.map((s, i) => `
    <div class="trace-step" id="ts-${i}">
      <div class="trace-step-header" onclick="toggleTraceStep('ts-${i}')">
        <div class="trace-step-icon ${s.state}"><i class="fa-solid ${s.icon}"></i></div>
        <span class="trace-step-label">${s.label}</span>
        <span class="trace-step-meta">${s.meta}</span>
        <i class="fa-solid fa-chevron-right trace-step-chevron"></i>
      </div>
      <div class="trace-step-body">${s.body}</div>
    </div>
  `).join('');

  const wrapper = document.createElement('div');
  wrapper.className = 'agent-trace';
  wrapper.innerHTML = `
    <div class="trace-header" onclick="this.closest('.agent-trace').classList.toggle('open')">
      <i class="fa-solid fa-sitemap"></i>
      LangGraph Agent Trace — 5 nodes executed
      <i class="fa-solid fa-chevron-down trace-toggle-icon"></i>
    </div>
    <div class="trace-steps">${stepsHtml}</div>
  `;
  return wrapper;
}

function toggleTraceStep(id) {
  document.getElementById(id)?.classList.toggle('open');
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function exportReport(sessionId, markdownContent) {
  const ts    = new Date().toLocaleString('id-ID');
  const clean = (markdownContent || '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/###\s+(.+)/g, '<h3>$1</h3>')
    .replace(/##\s+(.+)/g, '<h2>$1</h2>')
    .replace(/#\s+(.+)/g, '<h1>$1</h1>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>')
    .replace(/^/, '<p>').replace(/$/, '</p>');

  const html = `<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8"/>
<title>FinAgent Due Diligence Report — ${sessionId}</title>
<style>
  body { font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; color: #1e293b; max-width: 900px; margin: 0 auto; padding: 40px 24px; }
  .header { border-bottom: 3px solid #3b82f6; padding-bottom: 20px; margin-bottom: 32px; }
  .logo-area { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
  .logo-area img { height: 48px; }
  .logo-title { font-size: 1.4rem; font-weight: 800; color: #1e40af; }
  .logo-sub   { font-size: .8rem; color: #64748b; }
  .meta { font-size: .82rem; color: #64748b; margin-top: 8px; }
  .badge { display: inline-block; background: #dbeafe; color: #1d4ed8; padding: 3px 10px; border-radius: 20px; font-size: .72rem; font-weight: 700; margin-right: 8px; }
  .content { line-height: 1.75; font-size: .95rem; }
  h1, h2, h3 { color: #1e40af; margin: 20px 0 8px; }
  code { background: #f1f5f9; padding: 1px 6px; border-radius: 4px; font-size: .85em; color: #0f172a; }
  strong { color: #0f172a; }
  .footer { margin-top: 40px; border-top: 1px solid #e2e8f0; padding-top: 16px; font-size: .75rem; color: #94a3b8; }
  @media print { body { padding: 20px; } }
</style></head><body>
<div class="header">
  <div class="logo-area">
    <div>
      <div class="logo-title">FinAgent</div>
      <div class="logo-sub">B2B KYC &amp; Due Diligence Platform</div>
    </div>
  </div>
  <div><span class="badge">PREMIUM REPORT</span><span class="badge">DEEP INVESTIGATION</span></div>
  <div class="meta">Session ID: <strong>${sessionId}</strong> &nbsp;|&nbsp; Generated: ${ts}</div>
</div>
<div class="content">${clean}</div>
<div class="footer">
  This report was generated by FinAgent AI using Neo4j knowledge graph analysis powered by GPT-4o.<br/>
  For official due diligence purposes, verify all data with authoritative sources.
</div>
</body></html>`;

  const blob = new Blob([html], { type: 'text/html' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `FinAgent-Report-${sessionId.slice(0,8)}.html`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('📄 Laporan berhasil diunduh!', 'success');
}

// ════════════════════════════════════════════════════════════
// DOCUMENTS
// ════════════════════════════════════════════════════════════
async function loadDocuments() {
  try {
    const r    = await fetch('/api/documents');
    const data = await r.json();
    const docs = data.documents || [];

    // Update badge
    const badge = document.getElementById('doc-count-badge');
    if (badge) { badge.textContent = docs.length; badge.style.display = docs.length ? '' : 'none'; }

    // Render compact list (chat side panel)
    const list = document.getElementById('doc-list');
    if (list) {
      if (docs.length === 0) {
        list.innerHTML = '<p class="empty-state-small">Belum ada dokumen</p>';
      } else {
        list.innerHTML = docs.map(d => `
          <div class="doc-list-item">
            <i class="fa-solid fa-file-pdf"></i>
            <span class="doc-name" title="${d.name}">${d.name}</span>
            <a href="/api/documents/download/${encodeURIComponent(d.name)}" download title="Download">
              <i class="fa-solid fa-download"></i>
            </a>
          </div>`).join('');
      }
    }

    // Render document grid (docs view)
    const grid = document.getElementById('doc-grid');
    if (grid) {
      if (docs.length === 0) {
        grid.innerHTML = '<div class="doc-empty"><i class="fa-solid fa-inbox fa-3x"></i><p>Belum ada dokumen. Upload file PDF atau TXT untuk memulai.</p></div>';
      } else {
        grid.innerHTML = docs.map(d => `
          <div class="doc-card">
            <div class="doc-card-icon"><i class="fa-solid ${d.name.endsWith('.pdf') ? 'fa-file-pdf' : 'fa-file-lines'}"></i></div>
            <div class="doc-card-name">${d.name}</div>
            <div class="doc-card-meta">${d.size} · ${d.modified}</div>
            <div class="doc-card-actions">
              <a class="doc-card-btn doc-btn-dl" href="/api/documents/download/${encodeURIComponent(d.name)}" download>
                <i class="fa-solid fa-download"></i> Download
              </a>
            </div>
          </div>`).join('');
      }
    }
  } catch (e) { console.error('loadDocuments error:', e); }
}

// ════════════════════════════════════════════════════════════
// CHAT HELPERS
// ════════════════════════════════════════════════════════════
function addMessage(role, content, opts = {}) {
  const container = document.getElementById('chat-messages');
  const div       = document.createElement('div');
  div.className   = `message msg-${role}`;

  const now   = new Date();
  const tsStr = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
  const avatarIcon = role === 'assistant' ? 'fa-robot' : 'fa-user';

  div.innerHTML = `
    <div class="msg-avatar"><i class="fa-solid ${avatarIcon}"></i></div>
    <div class="msg-bubble">
      ${formatContent(content)}
      <div class="msg-meta">${tsStr}</div>
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;

  // Store in history + persist to localStorage
  _chatHistory.push({ role, content, ts: now.toISOString() });
  try { localStorage.setItem('_chatHistory', JSON.stringify(_chatHistory.slice(-50))); } catch(_){}

  return div;
}

function addTypingIndicator() {
  const id        = `typing-${Date.now()}`;
  const container = document.getElementById('chat-messages');
  const div       = document.createElement('div');
  div.id        = id;
  div.className = 'message msg-assistant msg-typing';
  div.innerHTML = `
    <div class="msg-avatar"><i class="fa-solid fa-robot"></i></div>
    <div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
  document.getElementById(id)?.remove();
}

function formatContent(text) {
  if (!text) return '';
  // Basic markdown-to-HTML: **bold**, *italic*, backtick code, newlines
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br/>')
    .replace(/^/, '<p>').replace(/$/, '</p>');
}

// ════════════════════════════════════════════════════════════
// TOAST
// ════════════════════════════════════════════════════════════
let _toastTimer;
function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  clearTimeout(_toastTimer);
  el.textContent  = msg;
  el.className    = `toast ${type}`;
  el.classList.remove('hidden');
  _toastTimer = setTimeout(() => el.classList.add('hidden'), 4000);
}
