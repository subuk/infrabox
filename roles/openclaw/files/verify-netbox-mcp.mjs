// Read-only integration verification. Never print API responses or credentials.
import fs from 'node:fs';
import { Client } from './netbox-mcp/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from './netbox-mcp/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';

const config = JSON.parse(fs.readFileSync('/etc/openclaw/openclaw.json', 'utf8'));
const expected = ['netbox_global_search', 'netbox_discover', 'netbox_describe', 'netbox_read', 'netbox_write'].sort();
const token = fs.readFileSync('/run/openclaw-secrets/netbox-token', 'utf8').trim();
let transport;
let client;
let diagnostics = '';
let phase = 'configuration';
try {
  if (!token || JSON.stringify(config).includes(token)) throw Error('Credential missing or persisted in config');
  const version = JSON.parse(fs.readFileSync('/opt/infrabox/netbox-mcp/node_modules/@zenixsolutions/netbox-mcp/package.json', 'utf8')).version;
  if (version !== process.argv[2]) throw Error('MCP version differs from pinned version');
  const server = config.mcp.servers.netbox;
  if (server.command !== '/usr/local/bin/infrabox-netbox-mcp' || !server.env.NETBOX_URL.startsWith('https://')) {
    throw Error('Unexpected MCP launch configuration');
  }
  const vaultToken = fs.readFileSync(process.env.VAULT_TOKEN_FILE, 'utf8').trim();
  const mount = process.env.OPENCLAW_VAULT_KV_MOUNT || 'kv';
  phase = 'openbao-read';
  const secret = await fetch(`${process.env.VAULT_ADDR}/v1/${mount}/data/openclaw/integrations/netbox`, {
    headers: {'X-Vault-Token': vaultToken}, signal: AbortSignal.timeout(30000)
  });
  if (!secret.ok || (await secret.json()).data.data.apiToken !== token) throw Error('Runtime and OpenBao token differ');
  transport = new StdioClientTransport({command: server.command,
    env: {...process.env, ...server.env}, stderr: 'pipe'});
  transport.stderr?.on('data', chunk => { diagnostics += chunk.toString(); });
  client = new Client({name: 'infrabox-read-only-verification', version: '1.0.0'});
  phase = 'mcp-connect';
  await client.connect(transport);
  phase = 'mcp-list-tools';
  const tools = await client.listTools();
  if (JSON.stringify(tools.tools.map(tool => tool.name).sort()) !== JSON.stringify(expected)) {
    throw Error('Unexpected NetBox MCP tools');
  }
  phase = 'netbox-read';
  const result = await client.callTool({name: 'netbox_read', arguments: {
    object_type: 'dcim.site', operation: 'list', limit: 1, response_format: 'json'
  }});
  if (result.isError) throw Error('MCP NetBox read failed');
  if (JSON.stringify(result).includes(token) || JSON.stringify(tools).includes(token) || diagnostics.includes(token)) {
    throw Error('MCP output contains credential');
  }
  console.log('Pinned NetBox MCP session, five tools, HTTPS read, and scoped OpenBao credential access verified');
} catch (error) {
  const code = Number.isInteger(error?.code) ? error.code : null;
  const flags = ['EACCES', 'ENOENT', 'ETIMEDOUT', 'ECONNREFUSED', 'CERTIFICATE_VERIFY_FAILED'].filter(value => diagnostics.includes(value));
  console.error(JSON.stringify({error: 'NetBox MCP read-only verification failed', phase, code, diagnostic_flags: flags}));
  process.exitCode = 1;
} finally {
  await client?.close();
  await transport?.close();
}
