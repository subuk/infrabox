import http from 'node:http';
import { isIPv4 } from 'node:net';

export const TOOL = 'infrabox_scan_subnet';
export function validateTarget(params) {
  if (!params || typeof params !== 'object' || Object.keys(params).length !== 1 || typeof params.subnet !== 'string') {
    throw Error('Provide only subnet: one canonical IPv4 CIDR, /24 through /32.');
  }
  const [ip, prefix, extra] = params.subnet.split('/');
  if (!isIPv4(ip) || !/^(2[4-9]|3[0-2])$/.test(prefix ?? '') || extra !== undefined) {
    throw Error('Only one IPv4 CIDR /24 through /32 is allowed (at most 256 addresses).');
  }
  const address = ip.split('.').reduce((n, octet) => n * 256 + Number(octet), 0);
  if (address % 2 ** (32 - Number(prefix)) !== 0) throw Error('Use the canonical network address; host bits must be zero.');
  return params.subnet;
}

export function request(path, data, signal) {
  return new Promise((resolve, reject) => {
    const body = data ? JSON.stringify(data) : undefined;
    const req = http.request({socketPath: '/run/infrabox-scanner/api.sock', path,
      method: body ? 'POST' : 'GET', signal,
      headers: body ? {'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body)} : {}}, res => {
      let size = 0;
      const chunks = [];
      res.on('data', chunk => {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) req.destroy(Error('Scanner result too large'));
        else chunks.push(chunk);
      });
      res.on('error', reject);
      res.on('end', () => {
        try {
          const result = JSON.parse(Buffer.concat(chunks).toString());
          if (res.statusCode !== 200) throw Error(result.error || 'Scanner unavailable');
          resolve(result);
        } catch (error) { reject(error); }
      });
    });
    req.setTimeout(190_000, () => req.destroy(Error('Scanner request timed out; do not retry without new approval.')));
    req.on('error', reject);
    req.end(body);
  });
}

export default {
  id: 'infrabox-subnet-scan',
  name: 'InfraBox subnet scanner',
  register(api) {
    api.on('before_tool_call', event => {
      if (event.toolName !== TOOL) return;
      let subnet;
      try { subnet = validateTarget(event.params); }
      catch (error) { return {block: true, blockReason: error.message}; }
      return {requireApproval: {
        title: `Scan ${subnet}`,
        description: `Discover responsive IPs, check 28 common TCP ports, and attempt Nmap OS fingerprinting on ${subnet}. This sends active probes, may trigger security alerts or disturb fragile devices, and OS guesses may be wrong. Allow once confirms this is your own local network and you approve this scan.`,
        severity: 'warning', allowedDecisions: ['allow-once', 'deny'], timeoutMs: 120_000,
      }};
    });
    api.registerTool({
      name: TOOL, label: 'Scan local subnet',
      description: 'Discover responsive IPv4 addresses, common TCP ports, and heuristic OS matches. Requires native one-time approval confirming the subnet is the user’s own local network. Never split a larger network into scans or retry without fresh approval. Observations do not authorize NetBox writes.',
      parameters: {type: 'object', additionalProperties: false, required: ['subnet'],
        properties: {subnet: {type: 'string', description: 'Canonical IPv4 CIDR, /24 through /32 (maximum 256 addresses).'}}},
      async execute(_id, params, signal) {
        const subnet = validateTarget(params);
        const result = await request('/scan', {subnet}, signal);
        return {content: [{type: 'text', text: JSON.stringify(result)}], details: result};
      },
    }, {optional: true});
  },
};
