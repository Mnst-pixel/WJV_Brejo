set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1
/usr/bin/python3 -I -B - <<'PY'
import importlib.util,json,os,pathlib,re,subprocess,sys

def fresh_source(base, work_name):
    import io, tarfile, hashlib, stat
    for parent in [base, *base.parents]:
        info = parent.lstat()
        assert stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
    archive_path = base / 'source.tar'
    info = archive_path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 and not info.st_mode & 0o022
    content = archive_path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == '2439ee31d6f146ce804b5fa207c464df01899dd17e630fe37212796de2009c20'
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
        members = archive.getmembers()
        assert len(members) < 5000 and len({entry.name for entry in members}) == len(members)
        for entry in members:
            path = pathlib.PurePosixPath(entry.name)
            assert not path.is_absolute() and '..' not in path.parts and (entry.isdir() or entry.isfile())
        work = base / work_name
        work.mkdir(mode=0o700)
        source = work / 'source'
        source.mkdir(mode=0o755)
        source.chmod(0o755)
        for entry in members:
            target = source.joinpath(*pathlib.PurePosixPath(entry.name).parts)
            if entry.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                target.chmod(0o755)
            else:
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(archive.extractfile(entry).read())
                target.chmod(0o644)
    return work, source

base=pathlib.Path('/opt/kairos/runtime/p0/20260918T031838Z-foundations')
work,source=fresh_source(base,'recovery-rehearsal')
spec=importlib.util.spec_from_file_location('routine',source/'scripts/backup-routine.py')
routine=importlib.util.module_from_spec(spec);spec.loader.exec_module(routine)
build=dict(line.split('=',1) for line in (base/'build-result.txt').read_text().splitlines() if '=' in line)
assert build['source_revision']=='10089ff4dae296caf35526bb2c8b51d458cff748'
assert re.fullmatch(r'sha256:[a-f0-9]{64}',build['candidate_image'])
before='/opt/kairos/runtime/baselines/p0p2-migration-20260918T031838Z-before'
after='/opt/kairos/runtime/baselines/p0p2-migration-20260918T031838Z-after'
environment=dict(os.environ)
environment.pop('DOCKER_HOST',None);environment.pop('DOCKER_CONTEXT',None)
environment['DOCKER_HOST']='unix:///var/run/docker.sock'
environment['COMPOSE_PROJECT_NAME']='kairos'
def command(name,args,env=None):
    path=work/(name+'.log')
    with open(path,'x',encoding='utf-8') as log:
        path.chmod(0o600)
        return subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,env=env or environment,timeout=1800).returncode
report={'source_revision':build['source_revision'],'image':build['candidate_image'],'work':str(work)}
passfile=work/'passphrase'
manifest=work/'no-changes.json'
routine.atomic_json(manifest,{'version':2,'release_commit':build['source_revision'],'config_changes':[],'network_changes':[],'edge_binding_change':None})
with routine.operation_lock('/opt/kairos/runtime/.operation.lock'):
    if command('before',['bash',str(source/'scripts/vps-snapshot.sh'),before]):
        raise RuntimeError('fresh baseline failed')
    try:
        report['backup_exit']=command('backup',['bash',str(source/'scripts/backup-predeploy.sh')])
        if report['backup_exit'] != 0: raise RuntimeError('backup failed; protected diagnostic retained')
        matches=re.findall(r'^KAIROS_PREDEPLOY_BACKUP=PASS scope=archive_created archive=(/srv/kairos/backups/kairos-predeploy-[0-9TZ]+-[a-f0-9]{12}\.tar\.gz\.enc)$',(work/'backup.log').read_text(),re.M)
        if len(matches)!=1: raise RuntimeError('backup receipt invalid')
        report['archive']=matches[0]
        with os.fdopen(os.open(passfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
            stream.write(routine.read_passphrase('/opt/kairos/secrets/.env'))
        probe_env=environment|{'KAIROS_RESTORE_API_IMAGE':build['candidate_image'],'KAIROS_RESTORE_API_REVISION':build['source_revision'],'KAIROS_RESTORE_SCOPED_ROLES':'1','DOCKER_HOST':'tcp://127.0.0.1:9','DOCKER_CONTEXT':'synthetic-forbidden','DOCKER_CONFIG':'/nonexistent-kairos-probe'}
        report['restore_exit']=command('restore',['bash',str(source/'scripts/verify-restore-isolated.sh'),report['archive'],str(passfile)],probe_env)
        lines=(work/'restore.log').read_text()
        receipts=re.findall(r'evidence=(/srv/kairos/backups/kairos-restore-[0-9TZ]+-[a-f0-9]{12}\.evidence)',lines)
        if receipts:
            report['restore_evidence']=receipts[-1]
            probe=pathlib.Path(receipts[-1])/'migration-probe.json'
            if probe.exists():
                value=json.loads(probe.read_text())
                report['migration_probe']={key:value[key] for key in ['status','planned_migrations','original_tables_checked','original_rows_checked','idempotent_rerun','excluded_expected_change','scoped_grants','scoped_runtime_api','not_verified']}
        if report['restore_exit']!=0: report['failure']='restore or migration probe failed; protected diagnostic retained'
    except Exception as error:
        report['failure']=type(error).__name__+' during controlled rehearsal; protected logs retained'
    finally:
        if passfile.exists():passfile.unlink()
        report['after_exit']=command('after',['bash',str(source/'scripts/vps-snapshot.sh'),after,before])
        report['no_touch_exit']=command('no-touch',['python3',str(source/'scripts/compare-release-snapshots.py'),before,after,'--manifest',str(manifest)]) if report['after_exit']==0 else 125
        report['status']='PASS' if all(report.get(key)==0 for key in ['backup_exit','restore_exit','after_exit','no_touch_exit']) and 'failure' not in report else 'FAIL'
        routine.atomic_json(work/'result.json',report)
        print(json.dumps(report,indent=2))
sys.exit(0 if report['status']=='PASS' else 1)
PY
