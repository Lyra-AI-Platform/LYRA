/**
 * Lyra — Personal AI Platform
 * Main frontend application
 */

// ─── State ───
const state = {
  conversationId: null,
  ws: null,
  isGenerating: false,
  selectedPersona: 'lyra-core',
  selectedLLM: null,
  uploadedFiles: [],
  conversations: [],
  currentStreamEl: null,
  currentStreamContent: '',
};

// ─── Init ───
document.addEventListener('DOMContentLoaded', async () => {
  setupMarked();
  await loadPersonas();
  await loadModels();
  await loadConversations();
  await newConversation();
  setupTempSlider();

  // Focus input
  document.getElementById('messageInput').focus();

  // Check health
  await checkHealth(true);

  // Start auto-learning status polling
  startLearningPoll();
});

function setupMarked() {
  marked.setOptions({
    breaks: true,
    gfm: true,
    highlight: (code, lang) => {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    },
  });
}

function setupTempSlider() {
  const slider = document.getElementById('tempSlider');
  const val = document.getElementById('tempValue');
  slider.addEventListener('input', () => { val.textContent = slider.value; });
}

// ─── Persona Management ───
async function loadPersonas() {
  try {
    const resp = await fetch('/api/models/');
    const data = await resp.json();
    renderPersonas(data.lyra_personas || []);
  } catch (e) {
    console.error('Failed to load personas:', e);
  }
}

function renderPersonas(personas) {
  const grid = document.getElementById('personaGrid');
  grid.innerHTML = personas.map(p => `
    <div class="persona-card ${p.id === state.selectedPersona ? 'active' : ''}"
         onclick="selectPersona('${p.id}', '${p.name}', '${p.icon}')"
         title="${p.description}">
      <span class="persona-icon">${p.icon}</span>
      <span class="persona-name">${p.name.replace('Lyra-', '')}</span>
    </div>
  `).join('');
}

function selectPersona(id, name, icon) {
  state.selectedPersona = id;
  document.querySelectorAll('.persona-card').forEach(c => c.classList.remove('active'));
  event.currentTarget.classList.add('active');
  document.getElementById('activePersonaLabel').textContent = `${icon} ${name}`;
}

// ─── LLM Model Management ───
async function loadModels() {
  try {
    const resp = await fetch('/api/models/');
    const data = await resp.json();
    renderModelSelect(data.local_models || [], data.loaded_model);
  } catch (e) {
    console.error('Failed to load models:', e);
  }
}

function renderModelSelect(models, loadedModel) {
  const select = document.getElementById('llmSelect');
  select.innerHTML = '<option value="">-- Select model --</option>';

  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.name;
    opt.textContent = `${m.name} (${m.size_gb}GB)`;
    if (m.name === loadedModel) opt.selected = true;
    select.appendChild(opt);
  });

  if (loadedModel) {
    updateModelBadge(loadedModel, true);
    state.selectedLLM = loadedModel;
  }
}

async function loadSelectedModel() {
  const select = document.getElementById('llmSelect');
  const modelName = select.value;
  if (!modelName) return;

  const btn = document.getElementById('loadModelBtn');
  btn.textContent = 'Loading...';
  btn.disabled = true;

  try {
    const resp = await fetch('/api/models/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: modelName, context_length: 8192, gpu_layers: -1 }),
    });
    const result = await resp.json();
    if (result.status === 'loaded' || result.status === 'already_loaded') {
      state.selectedLLM = modelName;
      updateModelBadge(modelName, true);
      showToast(`✅ ${modelName} loaded`);
    } else {
      showToast(`❌ ${result.message || 'Load failed'}`, 'error');
    }
  } catch (e) {
    showToast(`❌ Error: ${e.message}`, 'error');
  }

  btn.textContent = 'Load';
  btn.disabled = false;
}

function updateModelBadge(name, loaded) {
  const badge = document.getElementById('modelBadge');
  badge.textContent = loaded ? name : 'No model loaded';
  badge.className = loaded ? 'model-badge loaded' : 'model-badge';
}

// ─── Model Manager Modal ───
async function openModelManager() {
  document.getElementById('modelModal').style.display = 'flex';
  await renderModelGrid();
  // Refresh periodically while modal open
  const interval = setInterval(async () => {
    if (document.getElementById('modelModal').style.display === 'none') {
      clearInterval(interval);
      return;
    }
    await renderModelGrid();
  }, 3000);
}

async function renderModelGrid() {
  try {
    const resp = await fetch('/api/models/download/status');
    const data = await resp.json();
    const models = data.recommended || [];

    const grid = document.getElementById('modelGrid');
    grid.innerHTML = models.map(m => `
      <div class="model-card ${m.downloaded ? 'downloaded' : ''}">
        <div class="model-card-info">
          <h3>${m.name}</h3>
          <p>${m.description}</p>
          <div class="model-card-badges">
            <span class="badge badge-size">${m.size_gb}GB</span>
            <span class="badge badge-ram">${m.min_ram_gb}GB RAM</span>
            ${m.recommended ? '<span class="badge badge-rec">⭐ Recommended</span>' : ''}
          </div>
          ${m.downloading ? `
            <div class="progress-bar-wrap">
              <div class="progress-bar"><div class="progress-bar-fill" style="width:${m.download_progress}%"></div></div>
              <small style="color:var(--text-muted);font-size:11px">Downloading... ${m.download_progress}%</small>
            </div>
          ` : ''}
        </div>
        <div>
          ${m.downloaded
            ? `<button class="btn-small" onclick="useDownloadedModel('${m.filename}')">Use</button>`
            : m.downloading
              ? `<button class="btn-small" disabled>Downloading...</button>`
              : `<button class="btn-primary" onclick="downloadModel('${m.id}')">Download</button>`
          }
        </div>
      </div>
    `).join('');
  } catch (e) {
    console.error('Failed to load model grid:', e);
  }
}

async function downloadModel(modelId) {
  showToast(`⬇ Downloading ${modelId}... This may take a while.`);
  try {
    await fetch('/api/models/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId }),
    });
    await renderModelGrid();
  } catch (e) {
    showToast(`❌ Download error: ${e.message}`, 'error');
  }
}

async function downloadCustomModel() {
  const url = document.getElementById('customUrl').value.trim();
  const filename = document.getElementById('customFilename').value.trim();
  if (!url || !filename) { showToast('Enter URL and filename', 'error'); return; }

  showToast('⬇ Custom download started...');
  await fetch('/api/models/download/custom', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, filename }),
  });
}

async function useDownloadedModel(filename) {
  document.getElementById('llmSelect').innerHTML = `<option value="${filename}" selected>${filename}</option>`;
  await loadSelectedModel();
  closeModal('modelModal');
  await loadModels();
}

// ─── Conversations ───
async function loadConversations() {
  try {
    const resp = await fetch('/api/chat/conversations');
    const data = await resp.json();
    state.conversations = data.conversations || [];
    renderConversationList();
  } catch (e) {}
}

function renderConversationList() {
  const list = document.getElementById('convList');
  if (!state.conversations.length) {
    list.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px 4px">No conversations yet</div>';
    return;
  }
  list.innerHTML = state.conversations.map(c => `
    <div class="conv-item ${c.id === state.conversationId ? 'active' : ''}"
         onclick="loadConversation('${c.id}')">
      💬 ${escapeHtml(c.title || 'Untitled')}
    </div>
  `).join('');
}

async function newConversation() {
  try {
    const resp = await fetch('/api/chat/conversations/new', { method: 'POST' });
    const data = await resp.json();
    state.conversationId = data.conversation_id;

    // Clear UI
    document.getElementById('messages').innerHTML = `
      <div class="welcome-screen" id="welcomeScreen">
        <div class="welcome-logo">✦</div>
        <h1>Welcome to Lyra</h1>
        <p>Your private, intelligent AI running on your machine.</p>
        <div class="welcome-features">
          <div class="feature">🧠 Learns from every conversation</div>
          <div class="feature">📄 Analyze any file</div>
          <div class="feature">🌐 Search the web</div>
          <div class="feature">💻 Write & debug code</div>
        </div>
        <div class="welcome-hint">
          <strong>First time?</strong> Download a model from the sidebar to get started.
        </div>
      </div>`;

    // Clear files
    state.uploadedFiles = [];
    updateFilePreview();

    // Reconnect WebSocket
    connectWebSocket();
    await loadConversations();
  } catch (e) {
    console.error('Failed to create conversation:', e);
  }
}

async function loadConversation(convId) {
  state.conversationId = convId;

  try {
    const resp = await fetch(`/api/chat/conversations/${convId}`);
    const data = await resp.json();
    const messages = data.messages || [];

    const container = document.getElementById('messages');
    container.innerHTML = '';

    messages.forEach(m => {
      if (m.role === 'user' || m.role === 'assistant') {
        appendMessage(m.role, m.content, false);
      }
    });

    connectWebSocket();
    renderConversationList();
    scrollToBottom();
  } catch (e) {
    console.error('Failed to load conversation:', e);
  }
}

// ─── WebSocket ───
function connectWebSocket() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }

  if (!state.conversationId) return;

  const wsUrl = `ws://${window.location.host}/api/chat/ws/${state.conversationId}`;
  state.ws = new WebSocket(wsUrl);

  state.ws.onmessage = handleWSMessage;
  state.ws.onerror = (e) => { console.error('WS error:', e); };
  state.ws.onclose = () => {
    // Reconnect after delay if not intentional
    if (state.conversationId) {
      setTimeout(connectWebSocket, 2000);
    }
  };
}

function handleWSMessage(event) {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case 'start':
      hideThinking();
      startAssistantMessage(msg.model);
      break;

    case 'token':
      appendToken(msg.content);
      break;

    case 'done':
      finalizeAssistantMessage();
      setGenerating(false);
      loadConversations();
      break;

    case 'error':
      hideThinking();
      appendMessage('assistant', `❌ Error: ${msg.content}`);
      setGenerating(false);
      break;

    case 'status':
      updateThinkingLabel(msg.content);
      break;
  }
}

// ─── Message Sending ───
async function sendMessage() {
  const input = document.getElementById('messageInput');
  const message = input.value.trim();

  if (!message || state.isGenerating) return;

  // Check model loaded
  if (!state.selectedLLM) {
    showToast('⚠️ Please load a model first. Click "Download Models" to get one.', 'warn');
    return;
  }

  // Hide welcome screen
  const welcome = document.getElementById('welcomeScreen');
  if (welcome) welcome.remove();

  // Clear input
  input.value = '';
  autoResize(input);
  document.getElementById('charCount').textContent = '0';

  // Show user message
  appendMessage('user', message);

  // Show thinking
  setGenerating(true);
  showThinking();

  // Send via WebSocket
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    connectWebSocket();
    await new Promise(r => setTimeout(r, 500));
  }

  const payload = {
    message,
    model_id: state.selectedPersona,
    use_memory: document.getElementById('memoryToggle').checked,
    use_web_search: document.getElementById('searchToggle').checked,
    temperature: parseFloat(document.getElementById('tempSlider').value),
    max_tokens: 2048,
  };

  try {
    state.ws.send(JSON.stringify(payload));
  } catch (e) {
    hideThinking();
    appendMessage('assistant', `❌ Connection error. Try refreshing.`);
    setGenerating(false);
  }

  // Clear uploaded files after sending
  if (state.uploadedFiles.length > 0) {
    state.uploadedFiles = [];
    updateFilePreview();
  }
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
  const input = document.getElementById('messageInput');
  document.getElementById('charCount').textContent = input.value.length;
}

// ─── Message Rendering ───
function appendMessage(role, content, animate = true) {
  const container = document.getElementById('messages');
  const id = `msg-${Date.now()}`;

  const row = document.createElement('div');
  row.className = `message-row ${role}`;
  row.id = id;

  const avatar = role === 'user' ? '👤' : '✦';
  const name = role === 'user' ? 'You' : 'Lyra';
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  row.innerHTML = `
    <div class="message-meta">
      <div class="message-avatar">${avatar}</div>
      <strong>${name}</strong>
      <span>${time}</span>
    </div>
    <div class="message-bubble" id="bubble-${id}">
      ${renderMarkdown(content)}
    </div>
    <div class="message-actions">
      <button class="msg-action-btn" onclick="copyMessage('bubble-${id}')">Copy</button>
      ${role === 'assistant' ? `<button class="msg-action-btn" onclick="regenerate()">↺ Retry</button>` : ''}
    </div>
  `;

  container.appendChild(row);
  addCodeCopyButtons(row);
  highlightCode(row);
  scrollToBottom();

  return id;
}

function startAssistantMessage(modelName) {
  const container = document.getElementById('messages');
  const id = `msg-stream-${Date.now()}`;
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const row = document.createElement('div');
  row.className = 'message-row assistant';
  row.id = id;
  row.innerHTML = `
    <div class="message-meta">
      <div class="message-avatar">✦</div>
      <strong>Lyra</strong>
      <span>${time}</span>
    </div>
    <div class="message-bubble streaming-cursor" id="bubble-${id}"></div>
    <div class="message-actions" style="opacity:0">
      <button class="msg-action-btn" onclick="copyMessage('bubble-${id}')">Copy</button>
      <button class="msg-action-btn" onclick="regenerate()">↺ Retry</button>
    </div>
  `;

  container.appendChild(row);
  state.currentStreamEl = document.getElementById(`bubble-${id}`);
  state.currentStreamContent = '';
  state.currentStreamRow = row;
  scrollToBottom();
}

function appendToken(token) {
  if (!state.currentStreamEl) return;
  state.currentStreamContent += token;

  // Re-render markdown as tokens arrive (debounced for perf)
  state.currentStreamEl.innerHTML = renderMarkdown(state.currentStreamContent);
  scrollToBottom();
}

function finalizeAssistantMessage() {
  if (!state.currentStreamEl) return;

  // Remove streaming cursor class
  state.currentStreamEl.classList.remove('streaming-cursor');

  // Final render
  state.currentStreamEl.innerHTML = renderMarkdown(state.currentStreamContent);

  // Add code copy buttons, highlight
  addCodeCopyButtons(state.currentStreamRow);
  highlightCode(state.currentStreamRow);

  // Show message actions
  const actions = state.currentStreamRow.querySelector('.message-actions');
  if (actions) actions.style.opacity = '';

  state.currentStreamEl = null;
  state.currentStreamContent = '';
  state.currentStreamRow = null;
}

function renderMarkdown(content) {
  try {
    return marked.parse(content || '');
  } catch (e) {
    return escapeHtml(content || '');
  }
}

function addCodeCopyButtons(container) {
  container.querySelectorAll('pre').forEach(pre => {
    if (pre.querySelector('.copy-code-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'copy-code-btn';
    btn.textContent = 'Copy';
    btn.onclick = () => {
      const code = pre.querySelector('code');
      navigator.clipboard.writeText(code ? code.textContent : pre.textContent);
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
    };
    pre.style.position = 'relative';
    pre.appendChild(btn);
  });
}

function highlightCode(container) {
  container.querySelectorAll('pre code').forEach(block => {
    if (!block.dataset.highlighted) {
      hljs.highlightElement(block);
      block.dataset.highlighted = 'yes';
    }
  });
}

// ─── File Upload ───
async function handleFileUpload(event) {
  const files = Array.from(event.target.files);
  if (!files.length) return;

  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('conversation_id', state.conversationId || '');

    showToast(`📎 Processing ${file.name}...`);

    try {
      const resp = await fetch('/api/chat/upload', { method: 'POST', body: formData });
      const result = await resp.json();

      if (result.success) {
        state.uploadedFiles.push({ name: file.name, type: result.type, size: result.size });
        updateFilePreview();
        showToast(`✅ ${file.name} ready for analysis`);
      } else {
        showToast(`❌ ${result.error}`, 'error');
      }
    } catch (e) {
      showToast(`❌ Upload failed: ${e.message}`, 'error');
    }
  }

  // Reset input
  event.target.value = '';
}

function updateFilePreview() {
  const preview = document.getElementById('filePreview');
  const chips = document.getElementById('fileChips');

  if (!state.uploadedFiles.length) {
    preview.style.display = 'none';
    return;
  }

  preview.style.display = 'block';
  chips.innerHTML = state.uploadedFiles.map((f, i) => `
    <div class="file-chip">
      ${fileIcon(f.type)} ${f.name} <span style="color:var(--text-muted)">${f.size}</span>
      <button onclick="removeFile(${i})">✕</button>
    </div>
  `).join('');
}

function removeFile(index) {
  state.uploadedFiles.splice(index, 1);
  updateFilePreview();
}

function fileIcon(type) {
  const icons = { pdf: '📄', code: '💻', image: '🖼', csv: '📊', docx: '📝', text: '📃' };
  return icons[type] || '📎';
}

// ─── Memory ───
async function openMemoryView() {
  document.getElementById('memoryModal').style.display = 'flex';

  try {
    const resp = await fetch('/api/memory/stats');
    const stats = await resp.json();
    document.getElementById('memoryStats').innerHTML = `
      <strong>Memory Status:</strong> ${stats.enabled ? '✅ Active' : '❌ Disabled'}<br>
      <strong>Stored memories:</strong> ${stats.count || 0}<br>
      ${stats.path ? `<strong>Location:</strong> ${stats.path}` : ''}
    `;
  } catch (e) {}
}

async function searchMemory() {
  const query = document.getElementById('memorySearchInput').value.trim();
  if (!query) return;

  try {
    const resp = await fetch('/api/memory/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, n_results: 8 }),
    });
    const data = await resp.json();
    const results = data.results || [];

    document.getElementById('memoryResults').innerHTML = results.length
      ? results.map(r => `
          <div class="memory-result">
            ${escapeHtml(r.content)}
            <div class="memory-result-meta">
              Type: ${r.metadata?.type || '?'} • ${r.metadata?.timestamp?.slice(0,10) || ''}
            </div>
          </div>
        `).join('')
      : '<p style="color:var(--text-muted);font-size:13px">No memories found.</p>';
  } catch (e) {}
}

async function clearMemory() {
  if (!confirm('Clear ALL memories? This cannot be undone.')) return;
  try {
    await fetch('/api/memory/clear', { method: 'DELETE' });
    showToast('🧠 Memories cleared');
    closeModal('memoryModal');
  } catch (e) {
    showToast('❌ Failed to clear memory', 'error');
  }
}

// ─── Auto-Learning ───
let _learningPollInterval = null;

function startLearningPoll() {
  updateLearningStatus();
  _learningPollInterval = setInterval(updateLearningStatus, 5000);
}

async function updateLearningStatus() {
  try {
    const resp = await fetch('/api/learning/status');
    const data = await resp.json();

    // Sidebar dot
    const dot = document.getElementById('learningDot');
    if (dot) {
      dot.className = 'learning-dot ' + (data.running ? 'active' : 'paused');
    }

    // Activity text
    const actEl = document.getElementById('learningActivity');
    if (actEl) actEl.textContent = data.current_activity || 'idle';

    // Stats
    const factsEl = document.getElementById('factsCount');
    if (factsEl) factsEl.textContent = `${data.learned_count} facts`;
    const topicsEl = document.getElementById('topicsCount');
    if (topicsEl) topicsEl.textContent = `${data.topic_count} topics`;

    // Toggle button label
    const btn = document.getElementById('learnToggleBtn');
    if (btn) btn.textContent = data.running ? '⏸ Pause' : '▶ Resume';

  } catch (e) {
    // Server not ready yet
  }
}

async function toggleLearning() {
  try {
    const resp = await fetch('/api/learning/status');
    const data = await resp.json();
    if (data.running) {
      await fetch('/api/learning/stop', { method: 'POST' });
      showToast('⏸ Auto-learning paused');
    } else {
      await fetch('/api/learning/start', { method: 'POST' });
      showToast('▶ Auto-learning resumed');
    }
    updateLearningStatus();
  } catch (e) {}
}

async function addLearnTopic() {
  const input = document.getElementById('learnTopicInput');
  const topic = input.value.trim();
  if (!topic) return;

  await fetch('/api/learning/topic', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, priority: 8 }),
  });
  input.value = '';
  showToast(`🧠 Added topic: "${topic}" — Lyra will learn it soon`);
  updateLearningStatus();
}

async function crawlNow() {
  await fetch('/api/learning/crawl-now', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  showToast('⚡ Learning cycle started now!');
  updateLearningStatus();
}

async function openLearningPanel() {
  document.getElementById('learningModal').style.display = 'flex';
  await refreshLearningPanel();
}

async function refreshLearningPanel() {
  try {
    const resp = await fetch('/api/learning/status');
    const data = await resp.json();

    // Stats cards
    document.getElementById('learningModalStats').innerHTML = `
      <div class="lstat-card">
        <div class="lstat-value">${data.learned_count}</div>
        <div class="lstat-label">Facts Learned</div>
      </div>
      <div class="lstat-card">
        <div class="lstat-value">${data.crawl_count}</div>
        <div class="lstat-label">Crawl Cycles</div>
      </div>
      <div class="lstat-card">
        <div class="lstat-value">${data.topic_count}</div>
        <div class="lstat-label">Topics Tracked</div>
      </div>
    `;

    // Activity log
    const log = data.activity_log || [];
    document.getElementById('activityLog').innerHTML = log.length
      ? [...log].reverse().map(e => `
          <div class="activity-entry">
            <span class="activity-time">${e.time}</span>
            <span>${e.message}</span>
          </div>
        `).join('')
      : '<div style="color:var(--text-muted);font-size:12px;padding:6px">No activity yet. Start a conversation!</div>';

    // Topics grid
    const topics = data.top_topics || [];
    document.getElementById('topicsGrid').innerHTML = topics.length
      ? topics.map(t => {
          const cls = t.score >= 10 ? 'high' : t.score >= 5 ? 'med' : 'low';
          const crawled = t.crawled ? 'crawled' : '';
          return `
            <div class="topic-chip ${cls} ${crawled}" title="Score: ${t.score}${t.crawled ? ' (crawled)' : ''}">
              ${escapeHtml(t.topic)}
              <span class="topic-score">${t.score}</span>
            </div>
          `;
        }).join('')
      : '<span style="color:var(--text-muted);font-size:12px">Chat with Lyra to build topic list</span>';

  } catch (e) {}
}

async function crawlTopicNow() {
  const input = document.getElementById('crawlTopicInput');
  const topic = input.value.trim();
  if (!topic) return;

  await fetch('/api/learning/crawl-now', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topics: [topic] }),
  });
  input.value = '';
  showToast(`⚡ Crawling "${topic}" now...`);
  setTimeout(refreshLearningPanel, 2000);
}

async function crawlUrlNow() {
  const url = document.getElementById('crawlUrlInput').value.trim();
  const topic = document.getElementById('crawlUrlTopic').value.trim();
  if (!url) return;

  await fetch('/api/learning/crawl-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, topic }),
  });
  showToast(`🔗 Crawling URL: ${url}`);
}

async function crawlRssNow() {
  await fetch('/api/learning/crawl-rss', { method: 'POST' });
  showToast('📰 Reading RSS news feeds...');
}

async function clearTopics() {
  if (!confirm('Clear all tracked topics?')) return;
  await fetch('/api/learning/topics/clear', { method: 'DELETE' });
  showToast('Topics cleared');
  refreshLearningPanel();
}

async function setLearningInterval(minutes) {
  await fetch('/api/learning/interval', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval_minutes: parseInt(minutes) }),
  });
  showToast(`⏱ Crawl interval set to ${minutes} minutes`);
}

// ─── Status Check ───
async function checkHealth(silent = false) {
  try {
    const resp = await fetch('/api/health');
    const data = await resp.json();

    if (!silent) {
      document.getElementById('statusModal').style.display = 'flex';
      document.getElementById('statusBody').innerHTML = `
        <div class="status-item">
          <span>Server</span>
          <span class="status-ok">✅ Running</span>
        </div>
        <div class="status-item">
          <span>Model Loaded</span>
          <span class="${data.model_loaded ? 'status-ok' : 'status-warn'}">
            ${data.model_loaded ? `✅ ${data.current_model}` : '⚠️ No model'}
          </span>
        </div>
        <div class="status-item">
          <span>Memory System</span>
          <span class="${data.memory_enabled ? 'status-ok' : 'status-warn'}">
            ${data.memory_enabled ? `✅ ${data.memory_count} memories` : '⚠️ Disabled'}
          </span>
        </div>
        <div class="status-item">
          <span>Auto-Learning</span>
          <span class="${data.learning_running ? 'status-ok' : 'status-warn'}">
            ${data.learning_running
              ? `✅ Active — ${data.facts_learned} facts learned`
              : '⏸ Paused'}
          </span>
        </div>
        <div class="status-item">
          <span>Learning Activity</span>
          <span style="color:var(--text-secondary);font-size:12px">${data.learning_activity || 'idle'}</span>
        </div>
        <div class="status-item">
          <span>Access URL</span>
          <span>${window.location.origin}</span>
        </div>
      `;
    }

    if (data.model_loaded) {
      updateModelBadge(data.current_model, true);
      state.selectedLLM = data.current_model;
    }
  } catch (e) {
    if (!silent) showToast('❌ Server not responding', 'error');
  }
}

// ─── UI Helpers ───
function showThinking() {
  document.getElementById('thinkingBar').style.display = 'flex';
  document.getElementById('thinkingLabel').textContent = 'Lyra is thinking...';
}

function hideThinking() {
  document.getElementById('thinkingBar').style.display = 'none';
}

function updateThinkingLabel(text) {
  document.getElementById('thinkingLabel').textContent = text;
}

function setGenerating(val) {
  state.isGenerating = val;
  document.getElementById('sendBtn').disabled = val;
}

function scrollToBottom() {
  const messages = document.getElementById('messages');
  messages.scrollTop = messages.scrollHeight;
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('collapsed');
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  document.getElementById('charCount').textContent = el.value.length;
}

function clearChat() {
  if (confirm('Clear this conversation?')) newConversation();
}

function exportChat() {
  const messages = document.querySelectorAll('.message-row');
  let text = `Lyra Conversation Export\n${new Date().toLocaleString()}\n${'='.repeat(50)}\n\n`;

  messages.forEach(row => {
    const role = row.classList.contains('user') ? 'You' : 'Lyra';
    const bubble = row.querySelector('.message-bubble');
    if (bubble) {
      text += `${role}:\n${bubble.innerText}\n\n`;
    }
  });

  const blob = new Blob([text], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `lyra-chat-${Date.now()}.txt`;
  a.click();
}

function copyMessage(bubbleId) {
  const el = document.getElementById(bubbleId);
  if (el) {
    navigator.clipboard.writeText(el.innerText);
    showToast('Copied!');
  }
}

function regenerate() {
  showToast('Retry: clear chat and re-ask your question.');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

let toastTimer = null;
function showToast(message, type = 'info') {
  let toast = document.getElementById('lyra-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'lyra-toast';
    toast.style.cssText = `
      position: fixed; bottom: 24px; right: 24px;
      padding: 10px 18px; border-radius: 10px;
      font-size: 14px; font-weight: 500; z-index: 9999;
      transition: opacity 0.3s; max-width: 360px;
      background: #1e293b; border: 1px solid #334155;
      color: #e2e8f0; box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    `;
    document.body.appendChild(toast);
  }

  if (type === 'error') toast.style.borderColor = 'rgba(239,68,68,0.5)';
  else if (type === 'warn') toast.style.borderColor = 'rgba(245,158,11,0.5)';
  else toast.style.borderColor = '#334155';

  toast.textContent = message;
  toast.style.opacity = '1';

  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.opacity = '0'; }, 4000);
}
