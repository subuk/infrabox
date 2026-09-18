"""Native role catalog only; LDAP/OIDC own all account memberships."""
import json
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from users.models import Group, ObjectPermission

from infrabox_catalog import EDITOR_MODELS, READER_MODELS, HARDWARE_READS


def configure():
    changed = False
    with transaction.atomic():
        for role in ('admin', 'editor', 'reader'):
            group, created = Group.objects.get_or_create(name='infrabox:netbox:' + role)
            changed |= created
            if role == 'admin':
                continue  # Native authentication maps this group to superuser.
            models = EDITOR_MODELS if role == 'editor' else READER_MODELS
            actions = ['view', 'add', 'change', 'delete'] if role == 'editor' else ['view']
            permission, created = ObjectPermission.objects.get_or_create(name='InfraBox central ' + role, defaults={'actions': actions})
            changed |= created
            if permission.users.exists():
                raise RuntimeError('Central role permission has direct user assignments')
            desired = {'actions': actions, 'enabled': True, 'constraints': None,
                       'description': 'InfraBox LDAP/OIDC ' + role + ' role.'}
            if any(getattr(permission, key) != value for key, value in desired.items()):
                for key, value in desired.items():
                    setattr(permission, key, value)
                permission.save()
                changed = True
            types = {ContentType.objects.get_by_natural_key(*name.split('.')).pk for name in models}
            if set(permission.object_types.values_list('pk', flat=True)) != types:
                permission.object_types.set(types)
                changed = True
            if set(permission.groups.values_list('pk', flat=True)) != {group.pk}:
                permission.groups.set([group])
                changed = True
        permission, created = ObjectPermission.objects.get_or_create(name='InfraBox hardware read',
            defaults={'actions': ['view'], 'enabled': True, 'constraints': None})
        changed |= created
        if permission.actions != ['view'] or not permission.enabled or permission.constraints is not None or permission.users.exists():
            raise RuntimeError('Hardware read permission conflicts with managed contract')
        types = {ContentType.objects.get_by_natural_key(*name.split('.')).pk for name in HARDWARE_READS}
        if set(permission.object_types.values_list('pk', flat=True)) != types:
            permission.object_types.set(types)
            changed = True
        groups = set(Group.objects.filter(name__in=['infrabox:netbox:reader','infrabox:netbox:editor']).values_list('pk', flat=True))
        if set(permission.groups.values_list('pk', flat=True)) != groups:
            permission.groups.set(groups)
            changed = True
        def seed(model, slug, name, **defaults):
            nonlocal changed
            obj, created = apps.get_model(model).objects.get_or_create(slug=slug, defaults={'name': name, **defaults})
            changed |= created
            return obj
        # Fixed schemas belong to provisioning, never to the runner token.
        cf_model = apps.get_model('extras.CustomField')
        for name, kind in [('last_success', 'datetime'), ('source', 'text'), ('run', 'text'),
                           ('revision', 'text'), ('architecture', 'text')]:
            cf, created = cf_model.objects.get_or_create(name='discovery_' + name,
                defaults={'type': kind, 'label': 'Discovery ' + name.replace('_', ' ')})
            if cf.type != kind:
                raise RuntimeError('Discovery custom field schema conflict')
            changed |= created
            types = {ContentType.objects.get_by_natural_key(*name.split('.')).pk
                     for name in ('dcim.device', 'virtualization.virtualmachine')}
            if set(cf.object_types.values_list('pk', flat=True)) != types:
                cf.object_types.set(types)
                changed = True
        disk_identity, created = cf_model.objects.get_or_create(name='discovery_disk_identity',
            defaults={'type': 'text', 'label': 'Discovery disk identity'})
        if disk_identity.type != 'text':
            raise RuntimeError('Discovery disk identity schema conflict')
        changed |= created
        module_type = ContentType.objects.get_by_natural_key('dcim', 'module').pk
        if set(disk_identity.object_types.values_list('pk', flat=True)) != {module_type}:
            disk_identity.object_types.set([module_type])
            changed = True
        for name, properties in [('CPU', {'cores': {'type': 'integer', 'minimum': 1}}),
                                 ('Disk', {'capacity_bytes': {'type': 'integer', 'minimum': 1},
                                           'rotational': {'type': 'boolean'}}),
                                 ('RAM', {'capacity_mib': {'type': 'integer', 'minimum': 1},
                                          'technology': {'type': 'string'}})]:
            schema = {'type': 'object', 'properties': properties, 'additionalProperties': False}
            profile, created = apps.get_model('dcim.ModuleTypeProfile').objects.get_or_create(
                name='Discovery ' + name, defaults={'schema': schema})
            if profile.schema != schema:
                raise RuntimeError('Discovery module profile schema conflict')
            changed |= created
        manufacturer = seed('dcim.Manufacturer', 'infrabox-generic', 'InfraBox Generic',
                            description='Placeholder manufacturer; actual hardware has not been verified.')
        for name in ('Server', 'Hypervisor', 'NAS', 'Network Device'):
            obj, created = apps.get_model('dcim.DeviceType').objects.get_or_create(
                slug='infrabox-generic-' + name.lower().replace(' ', '-'),
                defaults={'manufacturer': manufacturer, 'model': 'Generic ' + name, 'u_height': 0,
                          'description': 'Temporary InfraBox device type used until hardware model is verified.'})
            if obj.manufacturer_id != manufacturer.pk:
                raise RuntimeError('Generic device type belongs to a different manufacturer')
            changed |= created
        for name in ('server', 'hypervisor', 'nas', 'router', 'switch', 'firewall'):
            seed('dcim.DeviceRole', name, name, color='607d8b')
        seed('extras.Tag', 'infrabox-managed', 'infrabox-managed', color='2196f3',
             description='Selected for later InfraBox automation; independent of OpenClaw access.')
        seed('extras.Tag', 'infrabox-user-provided', 'infrabox-user-provided', color='9e9e9e',
             description='Initial information supplied through conversational onboarding; not discovered.')
    return {'changed': changed}


print(json.dumps(configure()))
