/**
 * MCP Container Control Plane - Frontend JavaScript
 */

// ===== Markdown 初期化 =====
marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true,
    gfm: true,
});

// ===== State =====
let currentContainer = null;
let containers = [];
let pollTimer = null;
let isSending = false;
let pendingSpec = null;
let activeEventSource = null;

// ===== DOM Elements =====
const containerList = document.getElementById('containerList');
const chatArea = document.getElementById('chatArea');
const containerDetail = document.getElementById('containerDetail');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const headerTitle = document.getElementById('headerTitle');
const btnHome = document.getElementById('btnHome');

// ===== Initialize =====
document.addEventListener('DOMContentLoaded', () => {
    loadContainers();
    setupEventListeners();
    pollTimer = setInterval(loadContainers, 10000);
});

function setupEventListeners() {
    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
    });
    btnHome.addEventListener('click', showMainScreen);
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });
}

// ===== Snackbar =====
function showSnackbar(message, type = 'info') {
    const el = document.getElementById('snackbar');
    el.textContent = message;
    el.className = `snackbar show ${type}`;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.className = 'snackbar'; }, 3500);
}

// ===== Markdown レンダリング =====
function renderMarkdown(text) {
    try {
        return marked.parse(text);
    } catch (e) {
        return escapeHtml(text);
    }
}

/**
 * ストリーミング中: 最新3行だけコンパクトに表示
 * ツール呼び出しインジケーターと共存する（DOMを破壊しない）
 */
function renderStreamPreview(el, rawText) {
    const lines = rawText.split('\n').filter(l => l.trim() !== '');
    const last3 = lines.slice(-3);

    let previewDiv = el.querySelector('.stream-preview');
    if (!previewDiv) {
        previewDiv = document.createElement('div');
        previewDiv.className = 'stream-preview';
        el.appendChild(previewDiv);
    }
    previewDiv.innerHTML = `
        <div class="stream-preview-label">✨ AI が生成中…</div>
        <div class="stream-preview-lines">${last3.map(l => `<div>${escapeHtml(l)}</div>`).join('')}</div>`;
}

/**
 * 完了時: 全文を Markdown レンダリングして表示。
 * ツール呼び出しインジケーターは保持、ストリームプレビューは除去。
 */
function renderFinalResult(el, rawText, removeJson) {
    let text = rawText;
    if (removeJson) {
        text = text.replace(/```json\s*\n[\s\S]*?```/g, '').trim();
    }
    // ストリームプレビューを除去
    const preview = el.querySelector('.stream-preview');
    if (preview) preview.remove();

    if (!text) return;

    const resultDiv = document.createElement('div');
    resultDiv.className = 'final-result';
    resultDiv.innerHTML = renderMarkdown(text);
    resultDiv.querySelectorAll('pre code').forEach(block => {
        if (!block.dataset.highlighted) {
            hljs.highlightElement(block);
            block.dataset.highlighted = 'true';
        }
    });
    el.appendChild(resultDiv);
}

/**
 * ツール呼び出しインジケーターを表示
 */
function appendToolCallIndicator(el, container, tool, args) {
    // ストリームプレビューがあれば一旦除去（後で再追加）
    const preview = el.querySelector('.stream-preview');
    if (preview) preview.remove();

    const div = document.createElement('div');
    div.className = 'tool-call-indicator';
    const argsStr = args && Object.keys(args).length > 0
        ? ' (' + Object.entries(args).map(([k, v]) => `${escapeHtml(k)}=${escapeHtml(JSON.stringify(v))}`).join(', ') + ')'
        : '';
    div.innerHTML = `🔄 <strong>${escapeHtml(container)}/${escapeHtml(tool)}</strong>${argsStr} を実行中…`;
    el.appendChild(div);
}

/**
 * ツール実行結果を表示
 */
function updateToolCallResult(el, container, tool, result) {
    const indicators = el.querySelectorAll('.tool-call-indicator:not(.completed)');
    const last = indicators[indicators.length - 1];
    if (last) {
        last.classList.add('completed');
        last.innerHTML = `✅ <strong>${escapeHtml(container)}/${escapeHtml(tool)}</strong>`
            + `<div class="tool-call-result">${escapeHtml(result)}</div>`;
    }
}

// ===== コンテナ一覧 =====
async function loadContainers() {
    try {
        const response = await fetch('/api/containers');
        if (response.ok) {
            containers = await response.json();
            renderContainerList();
        }
    } catch (error) {
        containerList.innerHTML = '<li class="text-secondary">コンテナなし</li>';
    }
}

function renderContainerList() {
    if (containers.length === 0) {
        containerList.innerHTML = '<li class="text-secondary">コンテナなし</li>';
        return;
    }
    containerList.innerHTML = containers.map(c => {
        const statusIcon = { running: '🟢', stopped: '⚪', building: '🔨', error: '🔴', not_found: '⚪' }[c.status] || '⚪';
        const statusLabel = { running: 'Running', stopped: 'Stopped', building: 'Building', error: 'Error', not_found: 'Stopped' }[c.status] || c.status;
        const isRunning = c.status === 'running';
        const isStopped = c.status === 'stopped' || c.status === 'not_found';
        return `
            <li class="container-item ${currentContainer === c.name ? 'active' : ''}">
                <div class="container-item-top" onclick="selectContainer('${c.name}')">
                    <span class="container-item-name">${escapeHtml(c.name)}</span>
                    <span class="container-item-status ${c.status}">${statusIcon} ${statusLabel}</span>
                </div>
                <div class="container-item-actions">
                    ${isStopped ? `<button class="ci-btn ci-start" onclick="event.stopPropagation();containerAction('${c.name}','start')">▶ 起動</button>` : ''}
                    ${isRunning ? `<button class="ci-btn ci-stop" onclick="event.stopPropagation();containerAction('${c.name}','stop')">⏹ 停止</button>` : ''}
                    <button class="ci-btn ci-delete" onclick="event.stopPropagation();if(confirm('${c.name} を削除しますか？'))containerAction('${c.name}','delete')">✕ 削除</button>
                </div>
            </li>`;
    }).join('');
}

function selectContainer(name) {
    currentContainer = name;
    showContainerDetail(name);
    renderContainerList();
}

// ===== 画面切替 =====
function showMainScreen() {
    currentContainer = null;
    headerTitle.textContent = '🚀 MCP Container Creator';
    chatArea.style.display = 'flex';
    containerDetail.style.display = 'none';
    // ヘッダーを Home モードに戻す
    document.querySelector('.header').classList.remove('container-mode');
    const statusBadge = document.getElementById('statusBadge');
    if (statusBadge) { statusBadge.textContent = 'Ready'; statusBadge.className = 'status-badge'; }
    chatInput.placeholder = 'メッセージを入力... (Enterで送信)';
    renderContainerList();
}

function showContainerDetail(name) {
    headerTitle.textContent = '📦 ' + name;
    chatArea.style.display = 'none';
    containerDetail.style.display = 'flex';
    // ヘッダーをコンテナモードに切替
    document.querySelector('.header').classList.add('container-mode');
    chatInput.placeholder = `${name} に対する修正指示を入力...`;
    switchTab('chat');
    loadContainerActions(name);
}

// ===== タブ =====
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tabName);
    });
    const tabContent = document.getElementById('tabContent');
    if (!currentContainer) return;
    switch (tabName) {
        case 'chat': loadChatTab(currentContainer, tabContent); break;
        case 'tools': loadToolsTab(currentContainer, tabContent); break;
        case 'code':  loadCodeTab(currentContainer, tabContent); break;
        case 'logs':  loadLogsTab(currentContainer, tabContent); break;
        case 'scan':  loadScanTab(currentContainer, tabContent); break;
    }
}

// ===== コンテナ操作 =====
function loadContainerActions(name) {
    const container = containers.find(c => c.name === name);
    if (!container) return;
    const statusBadge = document.getElementById('statusBadge');
    if (statusBadge) {
        statusBadge.textContent = container.status;
        statusBadge.className = `status-badge ${container.status}`;
    }
}

async function containerAction(name, action) {
    try {
        const method = action === 'delete' ? 'DELETE' : 'POST';
        const url = action === 'delete'
            ? `/api/containers/${name}`
            : `/api/containers/${name}/${action}`;
        const resp = await fetch(url, { method });
        if (resp.ok) {
            const actionLabel = { start: '起動', stop: '停止', delete: '削除' }[action] || action;
            showSnackbar(`✅ ${name} を${actionLabel}しました`, 'success');
            await loadContainers();
            if (action === 'delete') {
                showMainScreen();
            } else if (currentContainer === name) {
                showContainerDetail(name);
            }
        } else {
            const err = await resp.json();
            showSnackbar(`❌ ${err.detail || 'エラーが発生しました'}`, 'error');
        }
    } catch (e) {
        showSnackbar(`❌ 通信エラー: ${e.message}`, 'error');
    }
}

// ===== Chat タブ（コンテナ編集チャット） =====
function loadChatTab(name, tabContent) {
    tabContent.innerHTML = `
        <div class="container-chat-area" id="containerChatArea">
            <div class="welcome-message edit-welcome" id="editWelcome">
                <h3>💬 ${escapeHtml(name)} を編集</h3>
                <p>AIに修正を依頼できます。コードの変更は自動的にビルド＆デプロイされます。</p>
                <div class="suggestions">
                    <div class="edit-suggestion" onclick="sendEditSuggestion(this)">🛡️ エラーハンドリングを強化して</div>
                    <div class="edit-suggestion" onclick="sendEditSuggestion(this)">📝 ツールの説明を詳しくして</div>
                    <div class="edit-suggestion" onclick="sendEditSuggestion(this)">➕ 新しいツールを追加して</div>
                </div>
            </div>
        </div>`;
}

function sendEditSuggestion(el) {
    chatInput.value = el.textContent.replace(/^[^\s]+\s/, '');
    sendMessage();
}

// ===== Tools タブ（Swagger 風テスト UI） =====
async function loadToolsTab(name, tabContent) {
    tabContent.innerHTML = '<p class="text-secondary text-center" style="padding:40px;">🔧 ツール読み込み中...</p>';
    try {
        const resp = await fetch(`/api/containers/${name}/tools`);
        if (!resp.ok) {
            tabContent.innerHTML = '<p class="text-secondary text-center" style="padding:40px;">ツール情報を取得できませんでした</p>';
            return;
        }
        const data = await resp.json();
        const tools = data.tools || [];
        if (tools.length === 0) {
            tabContent.innerHTML = '<p class="text-secondary text-center" style="padding:40px;">ツールが見つかりませんでした</p>';
            return;
        }
        tabContent.innerHTML = `
            <div class="tools-list">
                ${tools.map((tool, idx) => renderToolCard(name, tool, idx)).join('')}
            </div>`;
    } catch (e) {
        tabContent.innerHTML = `<p class="text-secondary text-center" style="padding:40px;">❌ エラー: ${escapeHtml(e.message)}</p>`;
    }
}

function renderToolCard(containerName, tool, idx) {
    const paramsHtml = (tool.parameters || []).map(p => `
        <div class="tool-param">
            <label>${escapeHtml(p.name)} <span class="param-type">(${escapeHtml(p.type)})</span></label>
            <input type="text" class="tool-input" id="param_${idx}_${p.name}"
                   placeholder="${escapeHtml(p.type)}" data-type="${escapeHtml(p.type)}">
        </div>`).join('');

    return `
        <div class="tool-card">
            <div class="tool-header">
                <span class="tool-name">🔧 ${escapeHtml(tool.name)}</span>
                <span class="tool-method">POST</span>
            </div>
            <p class="tool-desc">${escapeHtml(tool.description || 'No description')}</p>
            ${paramsHtml ? `<div class="tool-params">${paramsHtml}</div>` : ''}
            <div class="tool-actions">
                <button class="btn btn-primary btn-sm"
                        onclick="executeTool('${escapeHtml(containerName)}', '${escapeHtml(tool.name)}', ${idx}, ${JSON.stringify(tool.parameters || []).replace(/"/g, '&quot;')})">
                    ▶ 実行
                </button>
                <div class="tool-result" id="toolResult_${idx}" style="display:none;"></div>
            </div>
        </div>`;
}

async function executeTool(containerName, toolName, idx, params) {
    const resultDiv = document.getElementById(`toolResult_${idx}`);
    resultDiv.style.display = 'block';
    resultDiv.className = 'tool-result loading';
    resultDiv.textContent = '⏳ 実行中...';

    const args = {};
    for (const p of params) {
        const input = document.getElementById(`param_${idx}_${p.name}`);
        if (input && input.value) {
            let val = input.value;
            if (p.type === 'float' || p.type === 'int') val = Number(val);
            else if (p.type === 'bool') val = val.toLowerCase() === 'true';
            args[p.name] = val;
        }
    }

    try {
        const resp = await fetch(`/api/containers/${containerName}/tools/${toolName}/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ args }),
        });
        const data = await resp.json();

        if (data.error) {
            resultDiv.className = 'tool-result error';
            resultDiv.textContent = `❌ ${data.error}`;
        } else {
            // 結果にエラーパターンが含まれていたら ❌ 表示
            const resultStr = typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2);
            const isError = /エラー|error|exception|traceback|failed/i.test(resultStr);
            if (isError) {
                resultDiv.className = 'tool-result error';
                resultDiv.textContent = `❌ ${resultStr}`;
            } else {
                resultDiv.className = 'tool-result success';
                resultDiv.textContent = `✅ 結果: ${resultStr}`;
            }
        }
    } catch (e) {
        resultDiv.className = 'tool-result error';
        resultDiv.textContent = `❌ 通信エラー: ${e.message}`;
    }
}

// ===== Code タブ =====
async function loadCodeTab(name, tabContent) {
    tabContent.innerHTML = '<p class="text-secondary">読み込み中...</p>';
    try {
        const resp = await fetch(`/api/containers/${name}/code`);
        const data = await resp.json();
        tabContent.innerHTML = `
            <div style="display:flex;flex-direction:column;height:100%;gap:8px;padding:8px;">
                <textarea id="codeEditor" style="flex:1;font-family:'Fira Code',monospace;font-size:13px;
                    background:#1e1e2e;color:#cdd6f4;border:1px solid var(--border-color);border-radius:8px;
                    padding:12px;resize:none;tab-size:4;">${escapeHtml(data.code || '# コードなし')}</textarea>
                <div style="display:flex;gap:8px;">
                    <button class="btn btn-primary btn-sm" onclick="saveCode('${name}')">💾 保存のみ</button>
                    <button class="btn btn-success btn-sm" onclick="saveAndRebuild('${name}')">🚀 保存 & 再ビルド</button>
                </div>
            </div>`;
    } catch (e) {
        tabContent.innerHTML = '<p class="text-secondary">コード取得エラー</p>';
    }
}

async function saveCode(name) {
    const code = document.getElementById('codeEditor').value;
    try {
        const resp = await fetch(`/api/containers/${name}/code`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code }),
        });
        if (resp.ok) showSnackbar('✅ コードを保存しました', 'success');
        else {
            const err = await resp.json();
            showSnackbar(`❌ ${err.detail || '保存エラー'}`, 'error');
        }
    } catch (e) {
        showSnackbar(`❌ 通信エラー: ${e.message}`, 'error');
    }
}

async function saveAndRebuild(name) {
    const code = document.getElementById('codeEditor').value;
    try {
        const saveResp = await fetch(`/api/containers/${name}/code`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code }),
        });
        if (!saveResp.ok) {
            const err = await saveResp.json();
            showSnackbar(`❌ ${err.detail || '保存エラー'}`, 'error');
            return;
        }

        const configResp = await fetch(`/api/containers/${name}`);
        const config = await configResp.json();

        const buildResp = await fetch(`/api/build/${name}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                code: code,
                dependencies: config.dependencies || [],
                whitelist: config.whitelist || [],
                description: config.description || '',
            }),
        });

        if (buildResp.ok) {
            showSnackbar('🔨 再ビルドを開始しました', 'info');
            switchTab('chat');
            const chatAreaEl = document.getElementById('containerChatArea');
            if (chatAreaEl) {
                const welcome = chatAreaEl.querySelector('.welcome-message');
                if (welcome) welcome.remove();
                addContainerMessage(chatAreaEl, `🔨 コード変更による再ビルドを開始: ${name}`, 'assistant');
                monitorContainerBuild(name, chatAreaEl);
            }
        } else {
            const err = await buildResp.json();
            showSnackbar(`❌ ${err.detail || 'ビルド開始エラー'}`, 'error');
        }
    } catch (e) {
        showSnackbar(`❌ 通信エラー: ${e.message}`, 'error');
    }
}

// ===== Logs タブ =====
async function loadLogsTab(name, tabContent) {
    tabContent.innerHTML = '<p class="text-secondary">読み込み中...</p>';
    try {
        const resp = await fetch(`/api/containers/${name}/logs?tail=200`);
        const data = await resp.json();
        tabContent.innerHTML = `
            <div style="height:100%;overflow:auto;padding:8px;">
                <pre class="log-viewer">${escapeHtml(data.logs || 'ログなし')}</pre>
                <button class="btn btn-secondary btn-sm" style="margin-top:8px;" onclick="loadLogsTab('${name}', document.getElementById('tabContent'))">
                    🔄 更新
                </button>
            </div>`;
    } catch (e) {
        tabContent.innerHTML = '<p class="text-secondary">ログ取得エラー</p>';
    }
}

// ===== メッセージ送信（メイン / コンテナ両対応） =====
async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || isSending) return;
    if (currentContainer) sendContainerMessage(message);
    else sendMainMessage(message);
}

// ===== メイン画面チャット (AI SSE) =====
async function sendMainMessage(message) {
    isSending = true;
    sendBtn.disabled = true;
    pendingSpec = null;

    const welcomeMsg = chatArea.querySelector('.welcome-message');
    if (welcomeMsg) welcomeMsg.remove();

    addMessage(message, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto';

    const assistantDiv = document.createElement('div');
    assistantDiv.className = 'message assistant markdown-body';
    chatArea.appendChild(assistantDiv);

    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.innerHTML = '<span></span><span></span><span></span>';
    assistantDiv.appendChild(typingDiv);
    scrollToBottom();

    // ストリーミング蓄積用
    let rawText = '';

    try {
        const encodedMsg = encodeURIComponent(message);
        const eventSource = new EventSource(`/api/chat/stream?message=${encodedMsg}`);
        let firstChunk = true;

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.type === 'text') {
                if (firstChunk) { assistantDiv.innerHTML = ''; firstChunk = false; }
                rawText += data.content;
                renderStreamPreview(assistantDiv, rawText);
                scrollToBottom();
            }

            if (data.type === 'tool_call') {
                if (firstChunk) { assistantDiv.innerHTML = ''; firstChunk = false; }
                appendToolCallIndicator(assistantDiv, data.container, data.tool, data.args);
                scrollToBottom();
            }

            if (data.type === 'tool_result') {
                updateToolCallResult(assistantDiv, data.container, data.tool, data.result);
                scrollToBottom();
            }

            if (data.type === 'build_ready') {
                pendingSpec = data.spec;
                // ストリームプレビューを除去しスペックカードを追加
                const sp = assistantDiv.querySelector('.stream-preview');
                if (sp) sp.remove();
                appendSpecCard(assistantDiv, data.spec, 'build');
                scrollToBottom();
            }

            if (data.type === 'error') {
                if (firstChunk) assistantDiv.innerHTML = '';
                assistantDiv.classList.add('error');
                assistantDiv.textContent = data.content;
            }

            if (data.type === 'done') {
                eventSource.close();
                // build_ready がなかった場合は普通の回答をレンダリング
                if (!pendingSpec && rawText) {
                    renderFinalResult(assistantDiv, rawText, false);
                    scrollToBottom();
                }
                isSending = false;
                sendBtn.disabled = false;
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
            if (firstChunk) {
                assistantDiv.innerHTML = '';
                assistantDiv.classList.add('error');
                assistantDiv.textContent = '❌ 接続エラーが発生しました。GOOGLE_API_KEY が設定されているか確認してください。';
            }
            isSending = false;
            sendBtn.disabled = false;
        };
    } catch (e) {
        assistantDiv.innerHTML = '';
        assistantDiv.classList.add('error');
        assistantDiv.textContent = '❌ エラー: ' + e.message;
        isSending = false;
        sendBtn.disabled = false;
    }
}

// ===== コンテナ編集チャット =====
async function sendContainerMessage(message) {
    isSending = true;
    sendBtn.disabled = true;

    const chatAreaEl = document.getElementById('containerChatArea');
    if (!chatAreaEl) return;

    const welcomeMsg = chatAreaEl.querySelector('.welcome-message');
    if (welcomeMsg) welcomeMsg.remove();

    addContainerMessage(chatAreaEl, message, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto';

    const assistantDiv = document.createElement('div');
    assistantDiv.className = 'message assistant markdown-body';
    chatAreaEl.appendChild(assistantDiv);

    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.innerHTML = '<span></span><span></span><span></span>';
    assistantDiv.appendChild(typingDiv);
    scrollContainerChat(chatAreaEl);

    let rawText = '';

    try {
        const name = currentContainer;
        const encodedMsg = encodeURIComponent(message);
        const eventSource = new EventSource(`/api/containers/${name}/chat/stream?message=${encodedMsg}`);
        let firstChunk = true;

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.type === 'text') {
                if (firstChunk) { assistantDiv.innerHTML = ''; firstChunk = false; }
                rawText += data.content;
                renderStreamPreview(assistantDiv, rawText);
                scrollContainerChat(chatAreaEl);
            }

            if (data.type === 'tool_call') {
                if (firstChunk) { assistantDiv.innerHTML = ''; firstChunk = false; }
                appendToolCallIndicator(assistantDiv, data.container, data.tool, data.args);
                scrollContainerChat(chatAreaEl);
            }

            if (data.type === 'tool_result') {
                updateToolCallResult(assistantDiv, data.container, data.tool, data.result);
                scrollContainerChat(chatAreaEl);
            }

            if (data.type === 'update_ready') {
                // ストリームプレビューを除去しスペックカードを追加
                const sp = assistantDiv.querySelector('.stream-preview');
                if (sp) sp.remove();
                appendSpecCard(assistantDiv, data.spec, 'update', name);
                scrollContainerChat(chatAreaEl);
            }

            if (data.type === 'error') {
                if (firstChunk) assistantDiv.innerHTML = '';
                assistantDiv.classList.add('error');
                assistantDiv.textContent = data.content;
            }

            if (data.type === 'done') {
                eventSource.close();
                // update_ready がなかった場合は普通の回答をレンダリング
                if (rawText && !assistantDiv.querySelector('.spec-card')) {
                    renderFinalResult(assistantDiv, rawText, false);
                    scrollContainerChat(chatAreaEl);
                }
                isSending = false;
                sendBtn.disabled = false;
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
            if (firstChunk) {
                assistantDiv.innerHTML = '';
                assistantDiv.classList.add('error');
                assistantDiv.textContent = '❌ 接続エラー';
            }
            isSending = false;
            sendBtn.disabled = false;
        };
    } catch (e) {
        assistantDiv.innerHTML = '';
        assistantDiv.classList.add('error');
        assistantDiv.textContent = '❌ エラー: ' + e.message;
        isSending = false;
        sendBtn.disabled = false;
    }
}

// ===== スペックカード却下（折りたたみ） =====
function dismissSpecCard(btn) {
    const card = btn.closest('.spec-card');
    if (!card) return;

    // ヘッダーテキストを取得
    const header = card.querySelector('.spec-header');
    const headerText = header ? header.textContent : '仕様';

    // カード内容を非表示にして折りたたみバーに差し替え
    const content = card.innerHTML;
    card.dataset.collapsed = 'true';
    card.dataset.content = content;
    card.innerHTML = `
        <div class="spec-collapsed-bar" onclick="expandSpecCard(this)">
            <span>📦 ${escapeHtml(headerText.replace(/📋|📝/g, '').trim())} — スキップ済み</span>
            <span style="font-size:0.8rem;color:var(--text-secondary);">▶ クリックで展開</span>
        </div>`;
    card.style.padding = '0';

    showSnackbar('⏭️ スキップしました（クリックで再表示）', 'info');
}

function expandSpecCard(bar) {
    const card = bar.closest('.spec-card');
    if (!card || !card.dataset.content) return;
    card.innerHTML = card.dataset.content;
    card.style.padding = '';
    delete card.dataset.collapsed;
    delete card.dataset.content;
}

// ===== 仕様カード（build / update 共通） =====
function appendSpecCard(container, spec, mode, containerName) {
    const toolsHtml = (spec.tools || []).map(t => {
        const params = (t.parameters || []).map(p => `${p.name}: ${p.type}`).join(', ');
        return `
            <div class="spec-tool">
                <div class="spec-tool-signature">
                    🔧 <code>${escapeHtml(t.name)}(${escapeHtml(params)}) → str</code>
                </div>
                <p class="spec-tool-desc">${escapeHtml(t.description || '')}</p>
            </div>`;
    }).join('');

    let headerText, buttonHtml, extraMeta = '';
    if (mode === 'build') {
        headerText = `📋 ${escapeHtml(spec.name)}`;
        buttonHtml = `
            <div style="display:flex;gap:8px;margin-top:12px;">
                <button class="btn btn-success" onclick="startBuildFromChat()" style="flex:1;">🚀 ビルド＆デプロイ</button>
                <button class="btn btn-secondary" onclick="dismissSpecCard(this)" style="flex:1;">✋ ビルドしない</button>
            </div>`;
        const depsList = (spec.dependencies || []).length > 0
            ? `<p class="spec-meta">📦 依存パッケージ: ${spec.dependencies.map(d => `<code>${escapeHtml(d)}</code>`).join(', ')}</p>` : '';
        const wlList = (spec.whitelist || []).length > 0
            ? `<p class="spec-meta">🌐 許可ドメイン: ${spec.whitelist.map(d => `<code>${escapeHtml(d)}</code>`).join(', ')}</p>` : '';
        extraMeta = depsList + wlList;
    } else {
        headerText = '📝 コード修正';
        buttonHtml = `
            <div style="display:flex;gap:8px;margin-top:12px;">
                <button class="btn btn-success" onclick="applyEdit('${escapeHtml(containerName)}')" style="flex:1;">🚀 変更を適用 & 再ビルド</button>
                <button class="btn btn-secondary" onclick="dismissSpecCard(this)" style="flex:1;">✋ 適用しない</button>
            </div>`;
    }

    const cardDiv = document.createElement('div');
    cardDiv.className = 'spec-card';
    cardDiv.innerHTML = `
        <div class="spec-header">${headerText}</div>
        <p class="spec-description">${escapeHtml(spec.description || '')}</p>
        ${toolsHtml ? `<div class="spec-tools"><div class="spec-tools-title">ツール一覧</div>${toolsHtml}</div>` : ''}
        ${extraMeta}
        ${buttonHtml}`;
    container.appendChild(cardDiv);
    scrollToBottom();
}

// ===== ビルド & デプロイ =====
async function startBuildFromChat() {
    try {
        const resp = await fetch('/api/chat/build', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            addMessage(`❌ ${data.detail}`, 'assistant error');
            showSnackbar(`❌ ${data.detail}`, 'error');
            return;
        }
        showSnackbar(`🔨 ビルドを開始: ${data.name}`, 'info');
        addMessage(`🔨 ビルドを開始しました: ${data.name}`, 'assistant');
        monitorBuild(data.name);
    } catch (e) {
        addMessage('❌ ビルドリクエストエラー: ' + e.message, 'assistant error');
        showSnackbar('❌ ビルドリクエストエラー', 'error');
    }
}

function monitorBuild(name) {
    const progressDiv = document.createElement('div');
    progressDiv.className = 'message assistant';
    progressDiv.innerHTML = `
        <div class="build-progress-container">
            <div style="margin-bottom:8px;font-weight:600;">🔨 ビルド進捗: ${escapeHtml(name)}</div>
            <div class="build-progress-bar">
                <div class="build-progress-fill" id="buildProgressFill" style="width:0%"></div>
            </div>
            <div class="build-logs" id="buildLogs"></div>
        </div>`;
    chatArea.appendChild(progressDiv);
    scrollToBottom();

    const eventSource = new EventSource(`/api/build/${encodeURIComponent(name)}/status`);
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const fill = document.getElementById('buildProgressFill');
        if (fill) fill.style.width = data.progress + '%';

        const logs = document.getElementById('buildLogs');
        if (logs && data.logs && data.logs.length > 0) {
            for (const line of data.logs) {
                const p = document.createElement('div');
                p.textContent = line;
                p.style.cssText = 'padding:2px 0;border-bottom:1px solid var(--border-color);';
                logs.appendChild(p);
            }
            logs.scrollTop = logs.scrollHeight;
        }
        scrollToBottom();

        if (data.done) {
            eventSource.close();
            if (data.stage === 'completed') {
                addMessage(`✅ ${name} のビルド＆デプロイが完了しました！左のサイドバーに表示されます。`, 'assistant');
                showSnackbar(`✅ ${name} のデプロイ完了！`, 'success');
            } else if (data.stage === 'failed') {
                addMessage(`❌ ビルド失敗: ${data.error}`, 'assistant error');
                showSnackbar(`❌ ${name} のビルド失敗`, 'error');
            }
            loadContainers();
        }
    };
    eventSource.onerror = () => { eventSource.close(); };
}

async function applyEdit(name) {
    try {
        const resp = await fetch(`/api/containers/${name}/chat/apply`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            const chatAreaEl = document.getElementById('containerChatArea');
            if (chatAreaEl) addContainerMessage(chatAreaEl, `❌ ${data.detail}`, 'assistant error');
            showSnackbar(`❌ ${data.detail}`, 'error');
            return;
        }
        showSnackbar(`🔨 再ビルドを開始: ${data.name}`, 'info');
        const chatAreaEl = document.getElementById('containerChatArea');
        if (chatAreaEl) {
            addContainerMessage(chatAreaEl, `🔨 再ビルドを開始: ${data.name}`, 'assistant');
            monitorContainerBuild(name, chatAreaEl);
        }
    } catch (e) {
        const chatAreaEl = document.getElementById('containerChatArea');
        if (chatAreaEl) addContainerMessage(chatAreaEl, `❌ エラー: ${e.message}`, 'assistant error');
        showSnackbar(`❌ エラー: ${e.message}`, 'error');
    }
}

function monitorContainerBuild(name, chatAreaEl) {
    const progressDiv = document.createElement('div');
    progressDiv.className = 'message assistant';
    progressDiv.innerHTML = `
        <div class="build-progress-container">
            <div style="margin-bottom:8px;font-weight:600;">🔨 リビルド進捗: ${escapeHtml(name)}</div>
            <div class="build-progress-bar">
                <div class="build-progress-fill" id="editBuildFill" style="width:0%"></div>
            </div>
            <div class="build-logs" id="editBuildLogs"></div>
        </div>`;
    chatAreaEl.appendChild(progressDiv);
    scrollContainerChat(chatAreaEl);

    const eventSource = new EventSource(`/api/build/${encodeURIComponent(name)}/status`);
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const fill = document.getElementById('editBuildFill');
        if (fill) fill.style.width = data.progress + '%';

        const logs = document.getElementById('editBuildLogs');
        if (logs && data.logs && data.logs.length > 0) {
            for (const line of data.logs) {
                const p = document.createElement('div');
                p.textContent = line;
                p.style.cssText = 'padding:2px 0;border-bottom:1px solid var(--border-color);';
                logs.appendChild(p);
            }
            logs.scrollTop = logs.scrollHeight;
        }
        scrollContainerChat(chatAreaEl);

        if (data.done) {
            eventSource.close();
            if (data.stage === 'completed') {
                addContainerMessage(chatAreaEl, `✅ ${name} の再ビルド＆デプロイが完了しました！`, 'assistant');
                showSnackbar(`✅ ${name} の再デプロイ完了！`, 'success');
            } else if (data.stage === 'failed') {
                addContainerMessage(chatAreaEl, `❌ ビルド失敗: ${data.error}`, 'assistant error');
                showSnackbar(`❌ ${name} のビルド失敗`, 'error');
            }
            loadContainers();
        }
    };
    eventSource.onerror = () => { eventSource.close(); };
}

// ===== Scan タブ（Cisco mcp-scanner） =====
function loadScanTab(name, tabContent) {
    tabContent.innerHTML = `
        <div class="scan-area" id="scanArea">
            <div class="scan-header">
                <h3>🛡️ Cisco セキュリティスキャン</h3>
                <p class="scan-description">
                    Cisco AI Defense 製 mcp-scanner (YARA アナライザー) を使用して、
                    MCPツールの振る舞いレベルの脅威を動的に検出します。
                </p>
                <button class="btn btn-primary" id="scanBtn" onclick="runCiscoScan('${escapeHtml(name)}')">
                    🔍 スキャン実行
                </button>
            </div>
            <div class="scan-result-area" id="scanResultArea"></div>
        </div>`;
}

async function runCiscoScan(name) {
    const scanBtn = document.getElementById('scanBtn');
    const resultArea = document.getElementById('scanResultArea');

    scanBtn.disabled = true;
    scanBtn.textContent = '⏳ スキャン実行中...（最大60秒）';
    resultArea.innerHTML = `
        <div class="scan-loading">
            <div class="typing-indicator"><span></span><span></span><span></span></div>
            <p>MCPサーバーを起動してツールをスキャン中...</p>
        </div>`;

    try {
        const resp = await fetch(`/api/containers/${encodeURIComponent(name)}/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        if (!resp.ok) {
            const err = await resp.json();
            resultArea.innerHTML = `<div class="scan-error">❌ ${escapeHtml(err.detail || 'スキャンエラー')}</div>`;
            return;
        }

        const data = await resp.json();
        renderScanResult(resultArea, data);
    } catch (e) {
        resultArea.innerHTML = `<div class="scan-error">❌ 通信エラー: ${escapeHtml(e.message)}</div>`;
    } finally {
        scanBtn.disabled = false;
        scanBtn.textContent = '🔍 スキャン実行';
    }
}

function renderScanResult(container, data) {
    const severityConfig = {
        'SAFE':   { icon: '✅', color: '#28a745', label: '安全' },
        'LOW':    { icon: '🔵', color: '#17a2b8', label: '低リスク' },
        'MEDIUM': { icon: '🟡', color: '#ffc107', label: '中リスク' },
        'HIGH':   { icon: '🔴', color: '#dc3545', label: '高リスク' },
    };
    const config = severityConfig[data.severity] || severityConfig['SAFE'];

    // ツール別にグルーピング
    const toolMap = {};
    if (data.raw_results) {
        for (const r of data.raw_results) {
            if (r.tool_name) {
                toolMap[r.tool_name] = {
                    description: r.tool_description || '',
                    is_safe: r.is_safe,
                    findings: (data.findings || []).filter(f => f.tool_name === r.tool_name),
                };
            }
        }
    }

    // ツールカード生成
    const toolCards = Object.entries(toolMap).map(([toolName, info]) => {
        const toolSeverity = info.is_safe ? 'SAFE' : (
            info.findings.some(f => f.severity === 'HIGH') ? 'HIGH' :
            info.findings.some(f => f.severity === 'MEDIUM') ? 'MEDIUM' :
            info.findings.some(f => f.severity === 'LOW') ? 'LOW' : 'SAFE'
        );
        const tc = severityConfig[toolSeverity] || severityConfig['SAFE'];
        const findingsHtml = info.findings.length > 0
            ? info.findings.map(f => {
                const fc = severityConfig[f.severity] || severityConfig['LOW'];
                return `<div class="scan-finding">
                    <span class="scan-finding-severity" style="color:${fc.color}">${fc.icon} ${f.severity}</span>
                    <span class="scan-finding-pattern">${escapeHtml(f.pattern)}</span>
                    <p class="scan-finding-desc">${escapeHtml(f.description)}</p>
                </div>`;
            }).join('')
            : '<p class="scan-no-issues">問題は検出されませんでした</p>';

        return `
            <div class="scan-tool-card" style="border-left: 3px solid ${tc.color};">
                <div class="scan-tool-header">
                    <span class="scan-tool-name">🔧 ${escapeHtml(toolName)}</span>
                    <span class="scan-tool-badge" style="background:${tc.color}15;color:${tc.color};">${tc.icon} ${tc.label}</span>
                </div>
                ${info.description ? `<p class="scan-tool-desc">${escapeHtml(info.description)}</p>` : ''}
                <div class="scan-findings">${findingsHtml}</div>
            </div>`;
    }).join('');

    // 詳細JSONセクション
    const rawJson = data.raw_results
        ? `<details class="scan-raw-details">
            <summary>📊 詳細スキャン結果 (JSON)</summary>
            <pre class="scan-raw-json">${escapeHtml(JSON.stringify(data.raw_results, null, 2))}</pre>
           </details>`
        : '';

    container.innerHTML = `
        <div class="scan-result-card">
            <div class="scan-result-header" style="border-left: 4px solid ${config.color};">
                <div class="scan-result-title">${config.icon} セキュリティスキャン結果</div>
                <div class="scan-result-meta">
                    <span>コンテナ: <strong>${escapeHtml(data.container_name)}</strong></span>
                    <span class="scan-severity-badge" style="background:${config.color};color:#fff;">${data.severity}</span>
                </div>
                <p class="scan-summary">${escapeHtml(data.summary)}</p>
            </div>
            ${toolCards ? `<div class="scan-tools-section">
                <h4>ツール別結果</h4>
                ${toolCards}
            </div>` : ''}
            ${rawJson}
        </div>`;
}

// ===== メッセージ追加 =====
function addContainerMessage(chatAreaEl, content, classes) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${classes}`;
    messageDiv.textContent = content;
    chatAreaEl.appendChild(messageDiv);
    scrollContainerChat(chatAreaEl);
}

function scrollContainerChat(el) {
    if (el) el.scrollTop = el.scrollHeight;
}

function sendSuggestion(el) {
    chatInput.value = el.textContent;
    sendMessage();
}

function addMessage(content, classes) {
    const welcomeMsg = chatArea.querySelector('.welcome-message');
    if (welcomeMsg) welcomeMsg.remove();
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${classes}`;
    messageDiv.textContent = content;
    chatArea.appendChild(messageDiv);
    scrollToBottom();
}

function scrollToBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
}

// ===== ユーティリティ =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
