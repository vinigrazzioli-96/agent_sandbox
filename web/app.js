const statusEl = document.getElementById('status');
const chatLog = document.getElementById('chatLog');
const frame = document.getElementById('previewFrame');

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = `${role.toUpperCase()}: ${text}`;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setStatus(text) {
  statusEl.textContent = `Status: ${text}`;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || 'Erro na API');
  }
  return data;
}

document.getElementById('startBtn').onclick = async () => {
  try {
    const data = await api('/api/session/start', { method: 'POST', body: JSON.stringify({ start_vnc: true }) });
    setStatus(`sessão ativa (sandbox ${data.sandbox_id})`);
    addMessage('system', JSON.stringify(data));
  } catch (e) {
    setStatus(`erro ao iniciar: ${e.message}`);
  }
};

document.getElementById('stopBtn').onclick = async () => {
  try {
    await api('/api/session/stop', { method: 'POST' });
    frame.src = 'about:blank';
    chatLog.innerHTML = '';
    setStatus('sessão parada');
  } catch (e) {
    setStatus(`erro ao parar: ${e.message}`);
  }
};

document.getElementById('refreshBtn').onclick = async () => {
  try {
    const data = await api('/api/session');
    setStatus(data.active ? `ativa (sandbox ${data.sandbox_id})` : 'inativa');
    if (data.preview_url) frame.src = data.preview_url;
  } catch (e) {
    setStatus(`erro no refresh: ${e.message}`);
  }
};

document.getElementById('previewBtn').onclick = async () => {
  try {
    const port = Number(document.getElementById('previewPort').value);
    const data = await api('/api/session/preview', {
      method: 'POST',
      body: JSON.stringify({ port }),
    });
    frame.src = data.preview_url;
    addMessage('system', `Preview URL definida: ${data.preview_url}`);
  } catch (e) {
    setStatus(`erro no preview: ${e.message}`);
  }
};

document.getElementById('manualBtn').onclick = async () => {
  const url = document.getElementById('manualUrl').value.trim();
  if (!url) return;
  try {
    const data = await api('/api/session/embed', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
    frame.src = data.preview_url;
    addMessage('system', `Embed manual: ${data.preview_url}`);
  } catch (e) {
    setStatus(`erro no embed manual: ${e.message}`);
  }
};

document.getElementById('chatForm').onsubmit = async (event) => {
  event.preventDefault();
  const textarea = document.getElementById('message');
  const message = textarea.value.trim();
  if (!message) return;

  addMessage('user', message);
  textarea.value = '';

  try {
    setStatus('processando no agente...');
    const data = await api('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message, auto_preview_port: Number(document.getElementById('previewPort').value) }),
    });

    addMessage('assistant', data.summary);
    for (const result of data.command_results || []) {
      addMessage('tool', `$ ${result.command}\n${result.output}`);
    }

    if (data.preview_url) {
      frame.src = data.preview_url;
    }

    setStatus('execução concluída');
  } catch (e) {
    addMessage('error', e.message);
    setStatus('falha na execução');
  }
};
