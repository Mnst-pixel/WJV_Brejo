set -Eeuo pipefail
/usr/bin/python3 -I - <<'PY'
import datetime,fcntl,hashlib,json,os,pathlib,re,secrets,shutil,stat,subprocess,sys,time

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
source=base/'source'
revision='10089ff4dae296caf35526bb2c8b51d458cff748'
node_image='sha256:244cc2b53f46f9e876304391d17682b0ddae9ac33491f4857e25e35a36ba7995'
node_tag='node:24.19.0-alpine3.23'
env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','COMPOSE_PROJECT_NAME':'kairos'}
docker=['/usr/bin/docker','--host','unix:///var/run/docker.sock']
runid=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(6)
work,source=fresh_source(base,'web-build-'+runid)
tag='kairos-web:product-'+revision
name='kairos-test-web-'+runid
container=None
create_attempted=False
report={'commit':revision,'node_base':node_image,'source_archive_sha256':hashlib.sha256((base/'source.tar').read_bytes()).hexdigest(),'work':str(work),'production_deploy':False}
def execute(args,*,timeout=30):
    return subprocess.run(args,env=env,capture_output=True,text=True,timeout=timeout)
def checked(args):
    result=execute(args)
    if result.returncode:raise RuntimeError('fixed command failed; no command output forwarded')
    return result.stdout.strip()
def logged(label,args,timeout=900):
    path=work/(label+'.log')
    with path.open('x') as stream:
        path.chmod(0o600)
        return subprocess.run(args,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout).returncode
lock=os.open('/opt/kairos/runtime/.operation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:
    assert stat.S_ISREG(os.fstat(lock).st_mode) and os.fstat(lock).st_uid==0 and not os.fstat(lock).st_mode&0o077
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert source.resolve()==source and not source.is_symlink()
    assert all(path.is_dir() and not path.is_symlink() and path.stat().st_uid==0 and not path.stat().st_mode&0o022 for path in [base,source,source/'apps',source/'apps/web'])
    assert report['source_archive_sha256']=='2439ee31d6f146ce804b5fa207c464df01899dd17e630fe37212796de2009c20'
    assert shutil.disk_usage('/opt/kairos').free>10*1024**3
    assert int(next(line.split()[1] for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))>2400000
    assert 'source_revision='+revision in (base/'build-result.txt').read_text()
    assert execute(docker+['image','inspect',tag]).returncode!=0
    assert execute(docker+['container','inspect',name]).returncode!=0
    assert checked(docker+['image','inspect','--format','{{.Id}}',node_tag])==node_image
    # Match every web source byte to the committed archive before running npm/build.
    import tarfile
    with tarfile.open(base/'source.tar') as archive:
        expected={item.name:hashlib.sha256(archive.extractfile(item).read()).hexdigest() for item in archive if item.isfile() and item.name.startswith('apps/web/')}
    paths=list((source/'apps/web').rglob('*'))
    assert all(not path.is_symlink() and path.stat().st_uid==0 and not path.stat().st_mode&0o022 and (not path.is_file() or path.stat().st_nlink==1) for path in paths)
    actual={str(path.relative_to(source)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
    assert actual==expected
    before='/opt/kairos/runtime/baselines/web-'+runid+'-before'
    after='/opt/kairos/runtime/baselines/web-'+runid+'-after'
    assert logged('before',['bash',str(source/'scripts/vps-snapshot.sh'),before])==0
    manifest=work/'no-changes.json'
    manifest.write_text(json.dumps({'version':2,'release_commit':revision,'config_changes':[],'network_changes':[],'edge_binding_change':None}));manifest.chmod(0o600)
    report['no_touch_manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
    try:
        report['build_exit']=logged('build',docker+['build','--pull=false','--memory','1536m','--memory-swap','1536m','--cpuset-cpus','0','--build-arg','SOURCE_REVISION='+revision,'--tag',tag,'--file',str(source/'apps/web/Dockerfile'),str(source/'apps/web')])
        assert report['build_exit']==0
        report['image']=checked(docker+['image','inspect','--format','{{.Id}}',tag])
        assert re.fullmatch(r'sha256:[a-f0-9]{64}',report['image'])
        assert checked(docker+['image','inspect','--format','{{index .Config.Labels "org.opencontainers.image.revision"}}',report['image']])==revision
        assert checked(docker+['image','inspect','--format','{{.Id}}',node_tag])==node_image
        create_attempted=True
        container=checked(docker+['create','--name',name,'--pull','never','--label','com.kairos.web.probe='+runid,'--label','com.docker.compose.project=kairos','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','128','--memory','384m','--memory-swap','384m','--cpus','0.5','--tmpfs','/tmp:rw,nosuid,size=64m,uid=10001,gid=10001','--env','INTERNAL_API_URL=http://127.0.0.1:9','--env','KAIROS_DEMO_MODE=false',report['image']])
        assert re.fullmatch(r'[a-f0-9]{64}',container)
        assert checked(docker+['container','inspect','--format','{{.Config.User}}',container])=='10001:10001'
        checked(docker+['start',container])
        program=r'''(async()=>{
const root='http://127.0.0.1:3000';
const health=await fetch(root+'/app/api/health');if(health.status!==200||(await health.json()).status!=='ok')throw Error('health');
const login=await fetch(root+'/app/entrar');const html=await login.text();if(login.status!==200||login.headers.get('x-powered-by')||!html.includes('Kair'))throw Error('login');
const privatePage=await fetch(root+'/app',{redirect:'manual'});
if(!([307,308].includes(privatePage.status)&&privatePage.headers.get('location')==='/app/entrar'))throw Error('unauthenticated page did not fail closed');
const asset=html.match(/(?:src|href)="([^"]+\/static\/[^"?]+\.css)/)?.[1];if(!asset)throw Error('stylesheet missing');
const css=await fetch(new URL(asset,root));if(css.status!==200)throw Error('stylesheet unavailable');
console.log(JSON.stringify({status:'PASS',health:health.status,login:login.status,private_page:privatePage.status,stylesheet:css.status,powered_by_disclosure:false,api_unavailable_fails_closed:true}));
})().catch(()=>{console.error('bounded web smoke failed');process.exit(1)});'''
        smoke=None
        for attempt in range(30):
            smoke=execute(docker+['exec',container,'node','-e',program],timeout=15)
            if smoke.returncode==0:break
            time.sleep(1)
        assert smoke is not None and smoke.returncode==0
        report['smoke']=json.loads(smoke.stdout)
    except Exception as error:
        report['failure']=type(error).__name__+'; protected logs retained'
    finally:
        report['cleanup_exit']=0
        if create_attempted:
            try:
                # Reconcile by reserved name even if create succeeded but its response was lost.
                rows=checked(docker+['container','ls','--all','--no-trunc','--filter','name=^/'+name+'$','--format','{{.ID}}|{{.Names}}']).splitlines()
                assert len(rows)<=1
                if rows:
                    actual_id,actual_name=rows[0].split('|')
                    assert actual_name==name and re.fullmatch(r'[a-f0-9]{64}',actual_id)
                    assert not container or actual_id==container
                    owned=checked(docker+['container','inspect','--format','{{index .Config.Labels "com.kairos.web.probe"}}',actual_id])
                    assert owned==runid
                    report['cleanup_exit']=execute(docker+['rm','-f',actual_id]).returncode
            except Exception:
                report['cleanup_exit']=1
        report['after_exit']=logged('after',['bash',str(source/'scripts/vps-snapshot.sh'),after,before])
        report['no_touch_exit']=logged('no-touch',['python3',str(source/'scripts/compare-release-snapshots.py'),before,after,'--manifest',str(manifest)]) if report['after_exit']==0 else 125
    report['status']='PASS' if not report.get('failure') and all(report.get(key)==0 for key in ['build_exit','cleanup_exit','after_exit','no_touch_exit']) else 'FAIL'
    (work/'result.json').write_text(json.dumps(report,indent=2));(work/'result.json').chmod(0o600)
    print(json.dumps(report,indent=2))
finally:os.close(lock)
sys.exit(0 if report.get('status')=='PASS' else 1)
PY
