"""Native LDAP refresh and bounded inspection; never creates users or tokens directly."""
import json
import contextlib
import io
from django.contrib.auth import authenticate
from django.http import HttpRequest
from users.models import Token, User
from infrabox_catalog import EDITOR_MODELS, READER_MODELS, DISCOVERY_PERMISSIONS, HARDWARE_READS
from infrabox_auth import InfraBoxObjectPermissionBackend


def require(value, message):
    if not value:
        raise RuntimeError(message)


def snapshot(user):
    if not user:
        return None
    return (user.email, user.is_active, user.is_superuser, user.password,
            tuple(user.groups.order_by('name').values_list('name', flat=True)))


def main(c):
    before = snapshot(User.objects.filter(username=c['username']).first())
    user = authenticate(request=HttpRequest(), username=c['username'], password=c['password'])
    require(user is not None, 'Native service LDAP authentication failed')
    require(user.is_active and not user.is_superuser and not user.has_usable_password(),
            'Service account flags differ from the central contract')
    require(list(user.groups.values_list('name', flat=True)) == ['infrabox:netbox:' + c['role']],
            'Central service role is missing or has unexpected authority')
    require(not user.user_permissions.exists() and not user.object_permissions.exists(),
            'Service has direct permissions outside central roles')
    models = EDITOR_MODELS if c['role'] == 'editor' else READER_MODELS
    actions = ['view', 'add', 'change', 'delete'] if c['role'] == 'editor' else ['view']
    expected = {app + '.' + action + '_' + model for app, model in (name.split('.') for name in models) for action in actions}
    expected |= {app + '.view_' + model for app, model in (name.split('.') for name in HARDWARE_READS)}
    if c['username'] == 'svc-platform':
        expected = DISCOVERY_PERMISSIONS
    permissions = InfraBoxObjectPermissionBackend().get_object_permissions(user)
    require(set(permissions) == expected and all(value == [None] for value in permissions.values()),
            'Effective service permissions differ from the managed inventory envelope')
    require(set(user.get_all_permissions()) == expected,
            'Another native backend grants unexpected service permissions')
    changed = before != snapshot(user)
    if c['action'] == 'reconcile':
        return {'changed': changed}
    token, value = None, c.get('token', '')
    if value.startswith('nbt_') and '.' in value:
        key, plaintext = value[4:].split('.', 1)
        candidate = Token.objects.filter(version=2, key=key).first()
        if candidate:
            require(candidate.user_id == user.pk and candidate.description == c['description'],
                    'Token belongs to another identity or purpose')
            if candidate.validate(plaintext):
                token = candidate
    valid = bool(token and token.is_active and token.write_enabled == (c['role'] == 'editor' or c['username'] == 'svc-platform')
                 and token.expires is None and not token.allowed_ips)
    if c['action'] == 'inspect':
        return {'changed': changed, 'valid': valid}
    if c['action'] == 'finalize':
        require(valid, 'Replacement token must be verified before retirement')
        count = Token.objects.filter(user=user, description=c['description'], enabled=True).exclude(pk=token.pk).update(enabled=False)
        return {'changed': changed or bool(count)}
    raise RuntimeError('Unknown native service identity operation')


with contextlib.redirect_stdout(io.StringIO()):
    result = main(config)
print(json.dumps(result))
