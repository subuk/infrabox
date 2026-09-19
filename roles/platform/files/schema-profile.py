"""Executed by Core inside NetBox; runner receives no schema-write permissions."""
import contextlib
import io
import json
from django.db import transaction
from core.models import DataSource, DataFile
from extras.models import ConfigContextProfile

def reconcile(c):
    changed=False
    source,created=DataSource.objects.get_or_create(name='InfraBox Platform contract',defaults={
        'type':'git','source_url':c['git_url'],
        'parameters':{'branch':c['branch'],'username':c['username'],'password':c['password']},'ignore_rules':'', 'enabled':True})
    changed |= created
    if source.type!='git' or source.source_url not in (c['git_url'],'file:///run/platform-schema.git'):
        raise RuntimeError('Existing Platform data source identity differs')
    # Core selects the approved execution branch; NetBox clones it directly over verified HTTPS.
    # Only the schema file is retained; keep ignore rules derived from committed tree paths.
    desired={'source_url':c['git_url'],'parameters':{'branch':c['branch'],'username':c['username'],'password':c['password']},'sync_interval':None,
             'ignore_rules':c['ignore_rules'],'enabled':True}
    for key,value in desired.items():
        if getattr(source,key)!=value: setattr(source,key,value);changed=True
    if changed: source.full_clean();source.save()
    schema_path='schemas/config-context.schema.json'
    datafile=DataFile.objects.filter(source=source,path=schema_path).first()
    if changed or not datafile or datafile.hash!=c['schema_sha256']:
        source.sync();changed=True
    datafile=DataFile.objects.get(source=source,path=schema_path)
    if datafile.hash!=c['schema_sha256']:
        raise RuntimeError('Git DataFile differs from approved schema')
    profile,created=ConfigContextProfile.objects.get_or_create(name='InfraBox Platform')
    changed |= created
    if profile.data_file_id!=datafile.pk or profile.schema!=datafile.get_data():
        profile.data_file=datafile
        profile.sync_data()
        profile.full_clean();profile.save();changed=True
    # Verify compatibility without modifying any existing context assignment.
    from jsonschema import validate
    for context in profile.config_contexts.all(): validate(context.data,profile.schema)
    return {'changed':changed,'profile_id':profile.pk,'schema_sha256':datafile.hash}
with contextlib.redirect_stdout(io.StringIO()), transaction.atomic():
    result=reconcile(config)
print(json.dumps(result))
