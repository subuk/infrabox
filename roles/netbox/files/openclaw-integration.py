"""Runs inside NetBox's Django environment; only the parent receives credentials."""
import json
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from users.models import ObjectPermission, Token, User

MODELS = (
    'dcim.site', 'dcim.location', 'dcim.manufacturer', 'dcim.devicetype',
    'dcim.devicerole', 'dcim.device', 'dcim.interface', 'ipam.prefix',
    'ipam.ipaddress', 'ipam.vlan', 'virtualization.clustertype',
    'virtualization.cluster', 'virtualization.virtualmachine',
    'virtualization.vminterface', 'extras.tag', 'dcim.platform',
    'dcim.macaddress', 'extras.configcontext',
)
ACTIONS = ('view', 'add', 'change', 'delete')


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
    return bool(token and token.is_active and token.write_enabled
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
                   'description': 'InfraBox OpenClaw inventory and Config Context CRUD; no account administration.'}
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

        def seed(model, slug, name, **defaults):
            nonlocal changed
            obj, created = apps.get_model(model).objects.get_or_create(
                slug=slug, defaults={'name': name, **defaults})
            changed |= created
            return obj

        manufacturer = seed('dcim.Manufacturer', 'infrabox-generic', 'InfraBox Generic',
                            description='Placeholder manufacturer; actual hardware has not been verified.')
        for name in ('Server', 'Hypervisor', 'NAS', 'Network Device'):
            slug = 'infrabox-generic-' + name.lower().replace(' ', '-')
            device_type, created = apps.get_model('dcim.DeviceType').objects.get_or_create(
                slug=slug, defaults={'manufacturer': manufacturer, 'model': 'Generic ' + name,
                    'u_height': 0, 'description': 'Temporary InfraBox device type used until hardware model is verified.'})
            require(device_type.manufacturer_id == manufacturer.pk,
                    'Generic device type slug belongs to a different manufacturer')
            changed |= created
        for name in ('server', 'hypervisor', 'nas', 'router', 'switch', 'firewall'):
            seed('dcim.DeviceRole', name, name, color='607d8b')
        seed('extras.Tag', 'infrabox-managed', 'infrabox-managed', color='2196f3',
             description='Selected for later InfraBox automation; independent of OpenClaw access.')
        seed('extras.Tag', 'infrabox-user-provided', 'infrabox-user-provided', color='9e9e9e',
             description='Initial information supplied through conversational onboarding; not discovered.')
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
                      write_enabled=True, expires=None)
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
