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
