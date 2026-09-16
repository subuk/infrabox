import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../roles/nginx/files/identity/identity.js', import.meta.url), 'utf8');
async function page(metadata = {}, {stored = false, failSave = false} = {}) {
  const nodes = new Map(), requests = [], redirects = [], storage = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {value: '', hidden: true, handlers: {}, children: [],
      addEventListener(name, fn) { this.handlers[name] = fn; },
      append(value) { this.children.push(value); }, focus() {}});
    return nodes.get(id);
  }
  node('credentials').hidden = false;
  const config = {provider: 'infrabox', human_mount_accessor: 'ldap', clients: {
    gitea: {client_id: 'gitea', redirect_uris: ['https://git.example.com/callback']}}};
  const auth = {client_token: 'disposable-session', lease_duration: 3600};
  if (stored) storage.set('infrabox-human-session', JSON.stringify({token: auth.client_token, expires: Date.now() + 10000}));
  const context = {
    URL, URLSearchParams, Date, JSON,
    document: {getElementById: node, querySelectorAll: () => [], createElement: () => ({})},
    location: {pathname: '/login/', search: '?client_id=gitea&redirect_uri=https%3A%2F%2Fgit.example.com%2Fcallback&response_type=code&state=state',
      replace(url) { redirects.push(String(url)); }},
    sessionStorage: {getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    fetch: async (url, options) => {
      requests.push({url, options});
      let result, ok = true;
      if (url === '/login/config.json') result = config;
      else if (url.startsWith('/v1/auth/ldap-human/login/')) result = {auth};
      else if (url === '/v1/auth/token/lookup-self') result = {data: {policies: ['infrabox-human'], entity_id: 'own-id', ttl: 3600}};
      else if (url === '/v1/identity/entity/id/own-id') {
        if (options.method === 'POST') {
          ok = !failSave;
          if (ok) metadata = JSON.parse(options.body).metadata;
          result = {};
        } else result = {data: {metadata, aliases: [{mount_accessor: 'ldap', metadata: {name: 'matvey'}}]}};
      } else if (url.endsWith('/authorize')) result = {data: {code: 'authorization-code'}};
      else if (url.endsWith('/revoke-self')) result = {};
      else throw Error('Unexpected API request ' + url);
      return {ok, status: 200, json: async () => result};
    },
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return {node, requests, redirects, storage,
    submit: id => node(id).handlers.submit({preventDefault() {}})};
}

test('new login clears password, collects own profile, then continues OIDC', async () => {
  const p = await page();
  p.node('username').value = 'matvey'; p.node('password').value = 'disposable-password';
  await p.submit('credentials');
  assert.equal(p.node('password').value, '');
  assert.equal(p.node('profile').hidden, false);
  assert.equal(p.node('display_name').value, 'matvey');
  assert.deepEqual(p.redirects, []);
  p.node('email').value = 'matvey@example.com';
  await p.submit('profile');
  const write = p.requests.find(r => r.url.endsWith('/own-id') && r.options.method === 'POST');
  assert.deepEqual(JSON.parse(write.options.body), {metadata: {email: 'matvey@example.com', display_name: 'matvey'}});
  assert.equal(p.redirects[0], 'https://git.example.com/callback?code=authorization-code&state=state');
  assert.ok(!p.requests.some(r => /enrollment|mfa/.test(r.url)));
});

test('restored session with a profile continues without reentering password', async () => {
  const p = await page({email: 'matvey@example.com'}, {stored: true});
  assert.equal(p.redirects.length, 1);
  assert.ok(!p.requests.some(r => r.url.includes('/auth/ldap-human/login/')));
});

test('failed profile save stays on profile and cannot continue OIDC', async () => {
  const p = await page({}, {stored: true, failSave: true});
  p.node('email').value = 'matvey@example.com';
  await p.submit('profile');
  assert.equal(p.node('profile').hidden, false);
  assert.deepEqual(p.redirects, []);
  assert.match(p.node('message').textContent, /Не удалось сохранить/);
});
