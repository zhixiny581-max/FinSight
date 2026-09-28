// Minimal iFinD MCP client for the services used by this prototype.
// The authorization value is read by server.js from the local .env file.
const ENDPOINTS = {
  news: 'https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-news-mcp',
  stock: 'https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp',
  index: 'https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-index-mcp'
};
const ALLOWED_TOOLS = {
  news: new Set(['search_news']),
  stock: new Set(['search_stocks', 'get_stock_info', 'get_stock_performance', 'stock_highfreq_quotes']),
  index: new Set(['index_data', 'sector_data'])
};
const sessions = new Map();
let requestId = 0;

function authorization() {
  const value = process.env.IFIND_MCP_AUTHORIZATION || process.env.IFIND_API_KEY || '';
  if (!value.trim() || /your.*(?:key|token)|这里粘贴/i.test(value)) {
    throw new Error('IFIND_NOT_CONFIGURED');
  }
  return value.trim();
}

function decodeResponse(body, id, contentType) {
  if (contentType.includes('text/event-stream')) {
    for (const event of body.split(/\r?\n\r?\n/)) {
      const lines = event.split(/\r?\n/).filter(line => line.startsWith('data:'));
      if (!lines.length) continue;
      try {
        const message = JSON.parse(lines.map(line => line.slice(5).trimStart()).join('\n'));
        if (message.id === id) return message;
      } catch { /* Ignore unrelated progress events. */ }
    }
    throw new Error('IFIND_INVALID_RESPONSE');
  }
  const message = JSON.parse(body);
  if (id !== undefined && message.id !== id) throw new Error('IFIND_INVALID_RESPONSE');
  return message;
}

async function post(serverType, method, params, session, timeoutMs = 60000) {
  const id = method === 'notifications/initialized' ? undefined : ++requestId;
  const message = { jsonrpc: '2.0', method };
  if (id !== undefined) message.id = id;
  if (params !== undefined) message.params = params;
  const headers = {
    'Authorization': authorization(),
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream'
  };
  if (session?.id) headers['Mcp-Session-Id'] = session.id;
  if (session?.version) headers['MCP-Protocol-Version'] = session.version;
  const response = await fetch(ENDPOINTS[serverType], {
    method: 'POST', headers, body: JSON.stringify(message), redirect: 'error',
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (!response.ok) throw new Error(`IFIND_HTTP_${response.status}`);
  const body = await response.text();
  if (body.length > 4_000_000) throw new Error('IFIND_INVALID_RESPONSE');
  return {
    message: id === undefined || !body.trim()
      ? null : decodeResponse(body, id, response.headers.get('content-type') || ''),
    sessionId: response.headers.get('mcp-session-id')
  };
}

async function initialize(serverType) {
  const current = sessions.get(serverType);
  if (current) return current;
  const result = await post(serverType, 'initialize', {
    protocolVersion: '2024-11-05', capabilities: {},
    clientInfo: { name: 'finsight-news-prototype', version: '0.1.0' }
  }, null, 30000);
  const version = result.message?.result?.protocolVersion;
  if (!version) throw new Error('IFIND_INVALID_RESPONSE');
  const session = { id: result.sessionId, version };
  await post(serverType, 'notifications/initialized', undefined, session, 10000);
  sessions.set(serverType, session);
  return session;
}

async function call(serverType, toolName, args) {
  if (!ALLOWED_TOOLS[serverType]?.has(toolName)) throw new Error('IFIND_TOOL_NOT_ALLOWED');
  if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error('IFIND_INVALID_ARGUMENTS');
  let session = await initialize(serverType);
  let result;
  try {
    result = await post(serverType, 'tools/call', { name: toolName, arguments: args }, session, 90000);
  } catch (error) {
    // A cached MCP session can expire while the local server stays open.
    if (!/^IFIND_HTTP_(400|404)$/.test(error.message)) throw error;
    sessions.delete(serverType);
    session = await initialize(serverType);
    result = await post(serverType, 'tools/call', { name: toolName, arguments: args }, session, 90000);
  }
  const message = result.message;
  if (!message || message.error) {
    return { ok: false, status_code: 502, error: 'iFinD MCP request failed' };
  }
  return { ok: true, status_code: 200, data: message };
}

module.exports = { call };
