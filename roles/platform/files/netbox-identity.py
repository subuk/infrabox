"""Runs inside NetBox's Django environment; only the parent receives credentials."""
import json
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from users.models import ObjectPermission, Token, User

MODELS = (
    'dcim.region', 'dcim.sitegroup', 'dcim.platform', 'dcim.site', 'dcim.location', 'dcim.manufacturer', 'dcim.devicetype',
    'dcim.devicerole', 'dcim.device', 'dcim.interface', 'ipam.prefix',
    'ipam.ipaddress', 'ipam.vlan', 'virtualization.clustertype',
    'virtualization.clustergroup', 'virtualization.cluster', 'virtualization.virtualmachine',
    'virtualization.vminterface', 'extras.tag', 'extras.configcontext', 'tenancy.tenant',
)
ACTIONS = ('view',)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def expected_permissions():
    return {f'{app}.{action}_{model}' for app, model in
            (name.split('.') for name in MODELS) for action in ACTIONS}


def verify_user(user):
    require(user.is_active and not getattr(user, 'is_staff', False) and not user.is_superuser,
            'Integration identity has incorrect account flags')
    require(not user.has_usable_password(), 'Integration identity permits password login')
    require(not user.groups.exists() and not user.user_permissions.exists(),
            'Integration identity has additional group or Django permissions')
    require({name for name in user.get_all_permissions() if user.has_perm(name)} == expected_permissions(),
            'Integration identity effective permissions differ from the contract')


def lookup_token(value, user, description):
    if not value:
        return None
    if value.startswith('nbt_') and '.' in value:
        key, plaintext = value[4:].split('.', 1)
        token = Token.objects.filter(version=2, key=key).first()
    else:
        plaintext = value
        token = Token.objects.filter(version=1, plaintext=value).first()
    if token:
        require(token.user_id == user.pk and token.description == description,
                'Stored token belongs to another identity or integration')
        if token.validate(plaintext):
            return token
    return None


def healthy(token):
    return bool(token and token.is_active and not token.write_enabled
                and token.expires is None and not token.allowed_ips)


def reconcile(c):
    changed = False
    with transaction.atomic():
        user, created = User.objects.get_or_create(username=c['username'])
        changed |= created
        if created or not user.is_active or getattr(user, 'is_staff', False) or user.is_superuser or user.has_usable_password():
            user.is_active, user.is_superuser = True, False
            # NetBox 4.7 removed Django's staff flag; support it when present.
            if hasattr(user, 'is_staff'):
                user.is_staff = False
            user.set_unusable_password()
            user.save()
            changed = True
        for relation in (user.groups, user.user_permissions):
            if relation.exists():
                relation.clear()
                changed = True
        permission, created = ObjectPermission.objects.get_or_create(
            name=c['permission_name'], defaults={'actions': list(ACTIONS)})
        changed |= created
        require(not permission.users.exclude(pk=user.pk).exists() and not permission.groups.exists(),
                'Refusing to alter an integration permission shared with other identities')
        desired = {'actions': list(ACTIONS), 'enabled': True, 'constraints': None,
                   'description': 'InfraBox Platform read-only inventory and Config Context access.'}
        if any(getattr(permission, key) != value for key, value in desired.items()):
            for key, value in desired.items():
                setattr(permission, key, value)
            permission.save()
            changed = True
        types = {ContentType.objects.get_by_natural_key(*name.split('.')).pk for name in MODELS}
        if set(permission.object_types.values_list('pk', flat=True)) != types:
            permission.object_types.set(types)
            changed = True
        if set(user.object_permissions.values_list('pk', flat=True)) != {permission.pk}:
            user.object_permissions.set([permission])
            changed = True

        verify_user(User.objects.get(pk=user.pk))
    return {'changed': changed}


def main(c):
    if c['action'] == 'reconcile':
        return reconcile(c)
    user = User.objects.get(username=c['username'])
    verify_user(user)
    token = lookup_token(c.get('token'), user, c['description'])
    if c['action'] == 'inspect':
        return {'changed': False, 'valid': healthy(token)}
    if c['action'] == 'create':
        token = Token(user=user, description=c['description'], version=2,
                      write_enabled=False, expires=None)
        token.full_clean()
        token.save()
        return {'changed': True, 'token': token.get_auth_header_prefix().removeprefix('Bearer ') + token.token}
    if c['action'] == 'finalize':
        require(healthy(token), 'Cannot retire credentials before validating the current token')
        count = Token.objects.filter(user=user, description=c['description'], enabled=True).exclude(
            pk=token.pk).update(enabled=False)
        return {'changed': bool(count)}
    raise ValueError('Unknown integration action')


# The host management helper supplies config through stdin, never command arguments.
if 'config' in globals():
    print(json.dumps(main(config)))
