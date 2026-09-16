'use strict';
(() => {
  const byId = (id) => document.getElementById(id);
  const sessionKey = 'infrabox-human-session';
  let config, authorization, entityId = '', token = '', profile = {};
  const message = (text) => { byId('message').textContent = text; };
  const busy = (value) => document.querySelectorAll('button').forEach((b) => { b.disabled = value; });
  async function api(path, data, authToken = '') {
    const response = await fetch('/v1/' + path, {
      method: data === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...(authToken ? { 'X-Vault-Token': authToken } : {}) },
      body: data === undefined ? undefined : JSON.stringify(data),
      credentials: 'omit', cache: 'no-store', redirect: 'error',
    });
    if (!response.ok) throw new Error('request-failed');
    return response.status === 204 ? {} : response.json();
  }
  function requestedAuthorization() {
    const query = new URLSearchParams(location.search);
    if (!query.has('client_id')) {
      if (location.pathname !== '/login/') throw new Error('invalid-request');
      return null;
    }
    for (const key of query.keys()) if (query.getAll(key).length !== 1) throw new Error('invalid-request');
    const client = Object.values(config.clients).find((c) => c.client_id === query.get('client_id'));
    if (!client || !client.redirect_uris.includes(query.get('redirect_uri')) || query.get('response_type') !== 'code') {
      throw new Error('invalid-request');
    }
    const result = {};
    for (const key of ['client_id', 'redirect_uri', 'response_type', 'scope', 'state', 'nonce',
                       'code_challenge', 'code_challenge_method', 'max_age']) {
      if (query.has(key)) result[key] = query.get(key);
    }
    return result;
  }
  function showProfile() {
    byId('email').value = profile.email || '';
    byId('display_name').value = profile.display_name || '';
    byId('complete').hidden = true;
    byId('profile').hidden = false;
    byId('email').focus();
  }
  async function continueToApplication() {
    byId('profile').hidden = true;
    if (authorization) {
      try {
        const raw = await api('identity/oidc/provider/' + config.provider + '/authorize', authorization, token);
        const result = raw.data || raw;
        if (!result.code) throw new Error('authorization-denied');
        const target = new URL(authorization.redirect_uri);
        target.searchParams.set('code', result.code);
        if (authorization.state !== undefined) target.searchParams.set('state', authorization.state);
        location.replace(target.href);
        return;
      } catch {
        message('Вход в приложение не разрешён или оно недоступно. Проверьте назначенную роль и начните вход из приложения ещё раз.');
      }
    }
    byId('complete').hidden = false;
  }
  async function finish(auth) {
    token = auth.client_token;
    const lookup = (await api('auth/token/lookup-self', undefined, token)).data;
    if (!lookup.policies.includes('infrabox-human') || !lookup.entity_id) throw new Error('invalid-session');
    entityId = lookup.entity_id;
    byId('credentials').hidden = true;
    byId('logout').hidden = false;
    sessionStorage.setItem(sessionKey, JSON.stringify({ token, expires: Date.now() + Math.min(auth.lease_duration, lookup.ttl) * 1000 }));
    const entity = (await api('identity/entity/id/' + encodeURIComponent(entityId), undefined, token)).data;
    profile = entity.metadata || {};
    const alias = entity.aliases.find((item) => item.mount_accessor === config.human_mount_accessor);
    if (!profile.display_name) profile.display_name = alias?.metadata?.name || '';
    if (typeof profile.email !== 'string' || !profile.email.trim()) {
      showProfile();
      return;
    }
    await continueToApplication();
  }
  byId('credentials').addEventListener('submit', async (event) => {
    event.preventDefault(); busy(true); message('');
    try {
      const result = await api('auth/ldap-human/login/' + encodeURIComponent(byId('username').value.trim()),
        { password: byId('password').value });
      byId('password').value = '';
      if (!result.auth?.client_token || result.auth.mfa_requirement) throw new Error('unexpected-login-response');
      await finish(result.auth);
    } catch {
      byId('password').value = '';
      message('Не удалось завершить вход. Проверьте личный логин и пароль или повторите попытку позже.');
    } finally { busy(false); }
  });
  byId('profile').addEventListener('submit', async (event) => {
    event.preventDefault(); busy(true); message('');
    try {
      const current = (await api('identity/entity/id/' + encodeURIComponent(entityId), undefined, token)).data;
      profile = { ...(current.metadata || {}), email: byId('email').value.trim(),
                  display_name: byId('display_name').value.trim() };
      await api('identity/entity/id/' + encodeURIComponent(entityId), { metadata: profile }, token);
      await continueToApplication();
    } catch {
      message('Не удалось сохранить профиль. Повторите попытку; если сессия истекла, войдите снова.');
    } finally { busy(false); }
  });
  byId('edit-profile').addEventListener('click', () => { message(''); showProfile(); });
  byId('logout').addEventListener('click', async () => {
    busy(true);
    if (token) await api('auth/token/revoke-self', {}, token).catch(() => {});
    sessionStorage.removeItem(sessionKey);
    location.replace('/login/');
  });
  (async () => {
    busy(true);
    try {
      const response = await fetch('/login/config.json', { cache: 'no-store', credentials: 'omit', redirect: 'error' });
      if (!response.ok) throw new Error('configuration-unavailable');
      config = await response.json(); authorization = requestedAuthorization();
      for (const [name, client] of Object.entries(config.clients)) {
        const link = document.createElement('a');
        link.textContent = { grafana: 'Grafana', netbox: 'NetBox', gitea: 'Gitea' }[name] || name;
        link.href = new URL(client.redirect_uris[0]).origin;
        byId('apps').append(link);
      }
      const vault = document.createElement('a'); vault.textContent = 'OpenBao'; vault.href = '/ui/'; byId('apps').append(vault);
      const stored = JSON.parse(sessionStorage.getItem(sessionKey) || 'null');
      const forceLogin = new URLSearchParams(location.search).get('prompt') === 'login' || authorization?.max_age !== undefined;
      if (stored && stored.expires > Date.now() && !forceLogin) {
        try {
          const lookup = await api('auth/token/lookup-self', undefined, stored.token);
          if (!lookup.data.policies.includes('infrabox-human')) throw new Error('invalid-session');
          await finish({ client_token: stored.token, lease_duration: Math.min(lookup.data.ttl, (stored.expires - Date.now()) / 1000) });
        } catch { sessionStorage.removeItem(sessionKey); }
      }
      busy(false);
    } catch { message('Ссылка входа недействительна или сервис ещё не настроен. Откройте приложение и начните вход оттуда.'); }
  })();
})();
