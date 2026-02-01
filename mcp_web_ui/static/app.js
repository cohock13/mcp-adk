// MCP Creator Web UI - JavaScript
const API_BASE = '';

// 状態管理
let sessionId = null;
let isLoading = false;
let hasActiveSession = false;  // セッションが開始されているか

// DOM要素
const chatArea = document.getElementById('chatArea');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const resetBtn = document.getElementById('resetBtn');
const serverList = document.getElementById('serverList');
const modelBadge = document.getElementById('modelBadge');

// アラート要素
const topAlert = document.getElementById('topAlert');
const alertMessage = document.getElementById('alertMessage');
const alertAction = document.getElementById('alertAction');
const alertClose = document.getElementById('alertClose');

// モーダル要素
const codeModal = document.getElementById('codeModal');
const serverNameInput = document.getElementById('serverName');
const serverCodeInput = document.getElementById('serverCode');
const saveServerBtn = document.getElementById('saveServerBtn');

// 初期化
document.addEventListener('DOMContentLoaded', () => {
    loadServers();
    loadModelInfo();
    setupEventListeners();
    setupAlertListeners();
});

// アラートリスナー設定
function setupAlertListeners() {
    if (alertClose) {
        alertClose.addEventListener('click', hideAlert);
    }
    if (alertAction) {
        alertAction.addEventListener('click', () => {
            hideAlert();
            resetChat();
        });
    }
}

// アラート表示
function showAlert(message) {
    if (alertMessage) {
        alertMessage.textContent = message;
    }
    if (topAlert) {
        topAlert.classList.add('show');
    }
}

// アラート非表示
function hideAlert() {
    if (topAlert) {
        topAlert.classList.remove('show');
    }
}

// イベントリスナー設定
function setupEventListeners() {
    // 送信ボタン
    sendBtn.addEventListener('click', sendMessage);
    
    // Enterキーで送信（Shift+Enterで改行）
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    // 入力エリアの自動リサイズ
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
    });
    
    // リセットボタン
    resetBtn.addEventListener('click', resetChat);
    
    // サーバー保存ボタン
    saveServerBtn.addEventListener('click', saveServer);
    
    // モーダル閉じる
    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', () => closeModal(btn.closest('.modal-overlay')));
    });
    
    // モーダルオーバーレイクリックで閉じる
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal(overlay);
        });
    });
    
    // サジェスションクリック
    document.querySelectorAll('.suggestion').forEach(suggestion => {
        suggestion.addEventListener('click', () => {
            chatInput.value = suggestion.textContent;
            sendMessage();
        });
    });
}

// メッセージ送信
async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message || isLoading) return;
    
    // ウェルカムメッセージを非表示
    const welcome = document.querySelector('.welcome-message');
    if (welcome) welcome.remove();
    
    // ユーザーメッセージを表示
    appendMessage(message, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto';
    
    // ローディング表示
    setLoading(true);
    showTypingIndicator();
    
    // ストリーミングモードで送信
    await sendMessageStreaming(message);
}

// SSEを使ったストリーミング送信
async function sendMessageStreaming(message) {
    const params = new URLSearchParams({
        message: message,
        ...(sessionId && { session_id: sessionId })
    });
    
    let currentToolContainer = null;
    let responseText = '';
    let assistantMessageDiv = null;
    
    try {
        const response = await fetch(`${API_BASE}/api/chat/stream?${params}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const text = decoder.decode(value, { stream: true });
            const lines = text.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        
                        switch (data.type) {
                            case 'session':
                                sessionId = data.session_id;
                                hasActiveSession = true;
                                break;
                                
                            case 'tool_start':
                                // タイピングインジケーター削除
                                removeTypingIndicator();
                                
                                // ツール呼び出し開始を表示
                                if (!currentToolContainer) {
                                    currentToolContainer = document.createElement('div');
                                    currentToolContainer.className = 'tool-calls-container';
                                    chatArea.appendChild(currentToolContainer);
                                }
                                appendToolCallStart(currentToolContainer, data.name, data.arguments);
                                chatArea.scrollTop = chatArea.scrollHeight;
                                break;
                                
                            case 'tool_end':
                                // ツール完了を更新
                                updateToolCallEnd(currentToolContainer, data.name, data.result);
                                chatArea.scrollTop = chatArea.scrollHeight;
                                break;
                                
                            case 'text':
                                // タイピングインジケーター削除
                                removeTypingIndicator();
                                
                                responseText += data.content;
                                
                                // アシスタントメッセージを更新または作成
                                if (!assistantMessageDiv) {
                                    assistantMessageDiv = document.createElement('div');
                                    assistantMessageDiv.className = 'message assistant';
                                    chatArea.appendChild(assistantMessageDiv);
                                }
                                assistantMessageDiv.innerHTML = formatMessage(responseText);
                                chatArea.scrollTop = chatArea.scrollHeight;
                                break;
                                
                            case 'error':
                                removeTypingIndicator();
                                appendMessage(data.message, 'assistant', data.is_rate_limit ? 'warning' : 'error');
                                break;
                                
                            case 'done':
                                // ストリーミング完了
                                currentToolContainer = null;
                                loadServers();
                                break;
                        }
                    } catch (parseError) {
                        console.error('Error parsing SSE data:', parseError);
                    }
                }
            }
        }
        
    } catch (error) {
        console.error('Error:', error);
        removeTypingIndicator();
        appendMessage(error.message, 'assistant', 'error');
    } finally {
        setLoading(false);
    }
}

// ツール呼び出し開始を表示（進行中スタイル）
function appendToolCallStart(container, toolName, args) {
    const toolDiv = document.createElement('div');
    toolDiv.className = 'tool-call running';
    toolDiv.dataset.toolName = toolName;
    
    const header = document.createElement('div');
    header.className = 'tool-call-header';
    header.innerHTML = `
        <span class="tool-icon">
            <span class="tool-spinner"></span>
        </span>
        <span class="tool-name">${escapeHtml(toolName)}</span>
        <span class="tool-status">実行中...</span>
        <span class="tool-toggle">▼</span>
    `;
    header.onclick = () => {
        const details = toolDiv.querySelector('.tool-call-details');
        const toggle = header.querySelector('.tool-toggle');
        if (details.classList.contains('open')) {
            details.classList.remove('open');
            toggle.textContent = '▼';
        } else {
            details.classList.add('open');
            toggle.textContent = '▲';
        }
    };
    
    const details = document.createElement('div');
    details.className = 'tool-call-details';
    
    // 引数
    const argsSection = document.createElement('div');
    argsSection.className = 'tool-section';
    argsSection.innerHTML = `
        <div class="tool-section-title">引数:</div>
        <pre class="tool-content">${escapeHtml(JSON.stringify(args, null, 2))}</pre>
    `;
    details.appendChild(argsSection);
    
    // 結果プレースホルダー
    const resultSection = document.createElement('div');
    resultSection.className = 'tool-section tool-result-section';
    resultSection.innerHTML = `
        <div class="tool-section-title">結果:</div>
        <pre class="tool-content tool-result-placeholder">実行中...</pre>
    `;
    details.appendChild(resultSection);
    
    toolDiv.appendChild(header);
    toolDiv.appendChild(details);
    container.appendChild(toolDiv);
}

// ツール完了を更新
function updateToolCallEnd(container, toolName, result) {
    if (!container) return;
    
    const toolDiv = container.querySelector(`.tool-call[data-tool-name="${toolName}"]`);
    if (!toolDiv) return;
    
    // 進行中スタイルを削除
    toolDiv.classList.remove('running');
    toolDiv.classList.add('completed');
    
    // ヘッダーのアイコンとステータスを更新
    const header = toolDiv.querySelector('.tool-call-header');
    const iconSpan = header.querySelector('.tool-icon');
    iconSpan.innerHTML = '✅';
    
    const statusSpan = header.querySelector('.tool-status');
    statusSpan.textContent = '完了';
    statusSpan.classList.add('success');
    
    // 結果を更新
    const resultPlaceholder = toolDiv.querySelector('.tool-result-placeholder');
    if (resultPlaceholder) {
        resultPlaceholder.classList.remove('tool-result-placeholder');
        resultPlaceholder.textContent = formatToolResult(result);
    }
}

// メッセージを追加
function appendMessage(content, role, extraClass = '') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role} ${extraClass}`.trim();
    
    // Markdownをパース（簡易版）
    const formattedContent = formatMessage(content);
    messageDiv.innerHTML = formattedContent;
    
    chatArea.appendChild(messageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
}

// ツール呼び出しを表示
function appendToolCalls(toolCalls) {
    const container = document.createElement('div');
    container.className = 'tool-calls-container';
    
    toolCalls.forEach((tool, index) => {
        const toolDiv = document.createElement('div');
        toolDiv.className = 'tool-call';
        
        const header = document.createElement('div');
        header.className = 'tool-call-header';
        header.innerHTML = `
            <span class="tool-icon">🔧</span>
            <span class="tool-name">${escapeHtml(tool.name)}</span>
            <span class="tool-toggle">▼</span>
        `;
        header.onclick = () => {
            const details = toolDiv.querySelector('.tool-call-details');
            const toggle = header.querySelector('.tool-toggle');
            if (details.classList.contains('open')) {
                details.classList.remove('open');
                toggle.textContent = '▼';
            } else {
                details.classList.add('open');
                toggle.textContent = '▲';
            }
        };
        
        const details = document.createElement('div');
        details.className = 'tool-call-details';
        
        // 引数
        const argsSection = document.createElement('div');
        argsSection.className = 'tool-section';
        argsSection.innerHTML = `
            <div class="tool-section-title">引数:</div>
            <pre class="tool-content">${escapeHtml(JSON.stringify(tool.arguments, null, 2))}</pre>
        `;
        details.appendChild(argsSection);
        
        // 結果
        if (tool.result) {
            const resultSection = document.createElement('div');
            resultSection.className = 'tool-section';
            resultSection.innerHTML = `
                <div class="tool-section-title">結果:</div>
                <pre class="tool-content">${escapeHtml(formatToolResult(tool.result))}</pre>
            `;
            details.appendChild(resultSection);
        }
        
        toolDiv.appendChild(header);
        toolDiv.appendChild(details);
        container.appendChild(toolDiv);
    });
    
    chatArea.appendChild(container);
    chatArea.scrollTop = chatArea.scrollHeight;
}

// ツール結果のフォーマット
function formatToolResult(result) {
    try {
        // JSONの場合は整形
        const parsed = JSON.parse(result);
        return JSON.stringify(parsed, null, 2);
    } catch {
        // JSONでなければそのまま返す（長すぎる場合は切り詰め）
        if (result.length > 2000) {
            return result.substring(0, 2000) + '\n... (truncated)';
        }
        return result;
    }
}

// メッセージフォーマット（簡易Markdown）
function formatMessage(text) {
    // コードブロック
    text = text.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang || ''}">${escapeHtml(code.trim())}</code></pre>`;
    });
    
    // インラインコード
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // 太字
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // 改行
    text = text.replace(/\n/g, '<br>');
    
    return text;
}

// HTMLエスケープ
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// タイピングインジケーター表示
function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.id = 'typingIndicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    chatArea.appendChild(indicator);
    chatArea.scrollTop = chatArea.scrollHeight;
}

// タイピングインジケーター削除
function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

// ローディング状態設定
function setLoading(loading) {
    isLoading = loading;
    sendBtn.disabled = loading;
    chatInput.disabled = loading;
}

// チャットリセット
async function resetChat() {
    if (!confirm('チャット履歴をリセットしますか？')) return;
    
    try {
        await fetch(`${API_BASE}/api/chat/reset`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ session_id: sessionId })
        });
        
        sessionId = null;
        hasActiveSession = false;
        hideAlert();
        chatArea.innerHTML = `
            <div class="welcome-message">
                <h3>🔧 MCP Creator Agent</h3>
                <p>MCPサーバーを作成・管理するAIエージェントです。</p>
                <div class="suggestions">
                    <div class="suggestion">四則演算のMCPサーバーを作成して</div>
                    <div class="suggestion">天気取得APIのMCPを作って</div>
                    <div class="suggestion">MCPサーバーの一覧を見せて</div>
                </div>
            </div>
        `;
        
        // サジェスションのイベント再設定
        document.querySelectorAll('.suggestion').forEach(suggestion => {
            suggestion.addEventListener('click', () => {
                chatInput.value = suggestion.textContent;
                sendMessage();
            });
        });
        
    } catch (error) {
        console.error('Error resetting chat:', error);
    }
}

// MCPサーバー一覧読み込み
async function loadServers() {
    try {
        const response = await fetch(`${API_BASE}/api/servers`);
        const servers = await response.json();
        
        serverList.innerHTML = '';
        
        if (servers.length === 0) {
            serverList.innerHTML = '<li class="text-secondary text-center" style="padding: 20px;">MCPサーバーがありません</li>';
            return;
        }
        
        servers.forEach(server => {
            const li = document.createElement('li');
            li.className = `server-item ${server.active ? 'active' : ''}`;
            li.innerHTML = `
                <span class="server-name">
                    <span class="server-status ${server.active ? 'active' : ''}"></span>
                    ${server.name}
                </span>
                <div class="server-actions">
                    <button class="btn-icon" onclick="viewServer('${server.name}')" title="コードを表示">
                        📝
                    </button>
                    <button class="btn-icon" onclick="scanServer('${server.name}')" title="セキュリティスキャン">
                        🔍
                    </button>
                    <button class="btn-icon" onclick="toggleServer('${server.name}', ${server.active})" title="${server.active ? '停止' : '起動'}">
                        ${server.active ? '⏹️' : '▶️'}
                    </button>
                    <button class="btn-icon danger" onclick="deleteServer('${server.name}')" title="削除">
                        🗑️
                    </button>
                </div>
            `;
            serverList.appendChild(li);
        });
        
    } catch (error) {
        console.error('Error loading servers:', error);
    }
}

// モデル情報読み込み
async function loadModelInfo() {
    try {
        const response = await fetch(`${API_BASE}/api/model`);
        const data = await response.json();
        modelBadge.textContent = data.model;
    } catch (error) {
        console.error('Error loading model info:', error);
    }
}

// サーバーコード表示
async function viewServer(name) {
    try {
        const response = await fetch(`${API_BASE}/api/servers/${name}/code`);
        const data = await response.json();
        
        serverNameInput.value = data.name;
        serverCodeInput.value = data.code;
        
        openModal(codeModal);
        
    } catch (error) {
        console.error('Error viewing server:', error);
        alert('サーバーコードの取得に失敗しました');
    }
}

// サーバー起動/停止
async function toggleServer(name, isActive) {
    const endpoint = isActive ? 'deactivate' : 'activate';
    
    try {
        const response = await fetch(`${API_BASE}/api/servers/${name}/${endpoint}`, {
            method: 'POST'
        });
        
        if (response.ok) {
            loadServers();
            // アクティブセッション中にMCPサーバーの状態が変更された場合はアラート表示
            if (hasActiveSession) {
                showAlert('MCPサーバーの状態が変更されました。変更を反映するにはチャットをリセットしてください。');
            }
        } else {
            throw new Error('Failed to toggle server');
        }
        
    } catch (error) {
        console.error('Error toggling server:', error);
        alert('サーバーの状態変更に失敗しました');
    }
}

// サーバー削除
async function deleteServer(name) {
    if (!confirm(`MCPサーバー "${name}" を削除しますか？`)) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/servers/${name}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadServers();
        } else {
            throw new Error('Failed to delete server');
        }
        
    } catch (error) {
        console.error('Error deleting server:', error);
        alert('サーバーの削除に失敗しました');
    }
}

// サーバーのセキュリティスキャン
async function scanServer(name) {
    try {
        // ローディング表示
        appendMessage('🔍 セキュリティスキャンを実行中...', 'assistant', 'loading');
        
        const response = await fetch(`${API_BASE}/api/servers/${name}/scan`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error('Scan failed');
        }
        
        const result = await response.json();
        
        // ローディングメッセージを削除
        const loadingMsg = chatArea.querySelector('.message.loading:last-child');
        if (loadingMsg) {
            loadingMsg.remove();
        }
        
        // スキャン結果を表示
        displayScanResult(result);
        
    } catch (error) {
        console.error('Error scanning server:', error);
        
        // ローディングメッセージを削除
        const loadingMsg = chatArea.querySelector('.message.loading:last-child');
        if (loadingMsg) {
            loadingMsg.remove();
        }
        
        appendMessage('❌ セキュリティスキャンに失敗しました', 'assistant');
    }
}

// スキャン結果を表示
function displayScanResult(result) {
    const severityEmoji = {
        'SAFE': '✅',
        'LOW': '🔵',
        'MEDIUM': '🟡',
        'HIGH': '🔴'
    };
    
    let message = `## ${severityEmoji[result.severity]} セキュリティスキャン結果\n\n`;
    message += `**サーバー:** ${result.server_name}\n\n`;
    message += `**判定:** ${result.severity}\n\n`;
    message += `**サマリー:** ${result.summary}\n\n`;
    
    // 旧形式の表示も残す（互換性のため）
    if (result.findings && result.findings.length > 0) {
        message += `### 検出された問題 (${result.findings.length}件)\n\n`;
        
        result.findings.forEach((finding, index) => {
            const sev = finding.severity || 'UNKNOWN';
            message += `${index + 1}. **${severityEmoji[sev] || '⚪'} ${finding.pattern || finding.tool_name || '不明'}**\n`;
            message += `   - 説明: ${finding.description || 'N/A'}\n`;
            message += `   - 深刻度: ${sev}\n`;
            
            if (finding.lines && finding.lines.length > 0) {
                message += `   - 検出行: ${finding.lines.join(', ')}\n`;
            }
            
            message += '\n';
        });
    }
    
    // メッセージを表示
    appendMessage(message, 'assistant');
    
    // 生のスキャン結果を折り畳み可能なセクションとして追加
    if (result.raw_results && result.raw_results.length > 0) {
        const jsonStr = JSON.stringify(result.raw_results, null, 2);
        const detailsHtml = `
            <div class="scan-result-details">
                <details>
                    <summary style="cursor: pointer; padding: 10px; background: #f5f5f5; border-radius: 4px; margin: 10px 0;">
                        <strong>📊 詳細スキャン結果 (JSON)</strong> - クリックして展開
                    </summary>
                    <pre style="background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 4px; overflow-x: auto; margin-top: 10px;"><code class="language-json">${escapeHtml(jsonStr)}</code></pre>
                </details>
            </div>
        `;
        
        const detailsDiv = document.createElement('div');
        detailsDiv.className = 'message assistant';
        detailsDiv.innerHTML = detailsHtml;
        chatArea.appendChild(detailsDiv);
        chatArea.scrollTop = chatArea.scrollHeight;
    }
}

// サーバー保存
async function saveServer() {
    const name = serverNameInput.value.trim().replace('.py', '');
    const code = serverCodeInput.value;
    
    if (!name || !code) {
        alert('サーバー名とコードを入力してください');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/servers`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, code })
        });
        
        if (response.ok) {
            closeModal(codeModal);
            loadServers();
        } else {
            throw new Error('Failed to save server');
        }
        
    } catch (error) {
        console.error('Error saving server:', error);
        alert('サーバーの保存に失敗しました');
    }
}

// 新しいサーバー作成モーダル
function openNewServerModal() {
    serverNameInput.value = '';
    serverCodeInput.value = `from mcp.server.fastmcp import FastMCP

# MCPサーバーを作成
mcp = FastMCP("MyServer")

@mcp.tool()
def my_tool(param: str) -> str:
    """ツールの説明"""
    return f"Result: {param}"

if __name__ == "__main__":
    mcp.run()
`;
    openModal(codeModal);
}

// モーダル操作
function openModal(modal) {
    modal.classList.add('active');
}

function closeModal(modal) {
    modal.classList.remove('active');
}
