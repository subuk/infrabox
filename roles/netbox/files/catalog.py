"""Shared managed NetBox role model envelope."""
EDITOR_MODELS = (
    'dcim.site', 'dcim.location', 'dcim.manufacturer', 'dcim.devicetype',
    'dcim.devicerole', 'dcim.device', 'dcim.interface', 'ipam.prefix',
    'ipam.ipaddress', 'ipam.vlan', 'virtualization.clustertype',
    'virtualization.cluster', 'virtualization.virtualmachine',
    'virtualization.vminterface', 'extras.tag', 'dcim.platform',
    'dcim.macaddress', 'extras.configcontext',
)
READER_MODELS = tuple(m for m in EDITOR_MODELS if m != 'dcim.macaddress') + (
    'dcim.region', 'dcim.sitegroup', 'virtualization.clustergroup', 'tenancy.tenant',
)

HARDWARE_READS = ('dcim.module', 'dcim.modulebay', 'dcim.moduletype', 'dcim.moduletypeprofile', 'virtualization.virtualdisk')
READER_MODELS = tuple(set(READER_MODELS) | set(HARDWARE_READS))

# Dedicated trusted discovery identity: no deletes, no semantic catalog writes.
DISCOVERY_WRITES = {
    'dcim.device': ('change',), 'virtualization.virtualmachine': ('change',),
    'dcim.interface': ('add', 'change'), 'virtualization.vminterface': ('add', 'change'),
    'dcim.macaddress': ('add',), 'ipam.ipaddress': ('add',),
    'dcim.platform': ('add',), 'dcim.manufacturer': ('add',),
    'dcim.modulebay': ('add',), 'dcim.moduletype': ('add',),
    'dcim.module': ('add', 'change'),
    'virtualization.virtualdisk': ('add', 'change'),
}
DISCOVERY_READS = tuple(set(READER_MODELS) | set(DISCOVERY_WRITES) | {'dcim.moduletypeprofile', 'ipam.vrf'})
DISCOVERY_PERMISSIONS = {
    app + '.' + action + '_' + model
    for name in DISCOVERY_READS for app, model in [name.split('.')]
    for action in ('view',) + DISCOVERY_WRITES.get(name, ())
}
