set -Eeuo pipefail
/usr/bin/python3 -I - <<'PY'
import datetime,fcntl,hashlib,importlib.util,json,os,pathlib,re,stat,subprocess,sys,time
P=pathlib.Path
revision='c12e53a7416902315391d1b8c0a48603cbb1db6e'
checkout=P('/opt/kairos/releases')/revision
descriptor=P('/opt/kairos/runtime/releases')/('product-'+revision)
secret_dir=P('/opt/kairos/secrets')/('product-'+revision)
base=P('/opt/kairos/runtime/p0/20260911T042557Z-foundations')
work=base/'mount-verification'
env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent','DOCKER_HOST':'unix:///var/run/docker.sock','COMPOSE_PROJECT_NAME':'kairos','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
os.environ.clear();os.environ.update(env);os.umask(0o077);sys.dont_write_bytecode=True
docker=['/usr/bin/docker','--host','unix:///var/run/docker.sock']
runid=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
report={'commit':revision,'production_deploy':False,'checks':{},'cleanup':{}}
created={}
def require(condition):
    if not condition:raise RuntimeError('mount verification invariant failed; details withheld')
def protected(path,directory=False):
    info=path.lstat()
    require(info.st_uid==0 and not info.st_mode&0o022 and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink==1))
    for parent in path.parents:
        info=parent.lstat();require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022)
def run(args,input=None,timeout=30):
    return subprocess.run(args,input=input,env=env,capture_output=True,text=True,timeout=timeout)
def checked(args,input=None):
    result=run(args,input);require(result.returncode==0);return result.stdout.strip()
def module(name,filename):
    path=checkout/'scripts'/filename
    protected(path)
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def logged(label,args):
    with (work/(label+'.log')).open('x') as stream:
        return subprocess.run(args,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=120).returncode
def create(kind,image,options,command):
    name='kairos-test-mount-'+kind+'-'+runid
    require(not checked(docker+['ps','-aq','--filter','name=^/'+name+'$']))
    created[name]={'id':None,'image':image}
    identity=checked(docker+['create','--name',name,'--pull','never','--label','com.docker.compose.project=kairos','--label','com.kairos.mount.probe='+runid,'--network','none','--no-healthcheck','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','192m','--memory-swap','192m','--cpus','0.5',*options,image,*command])
    require(re.fullmatch(r'[a-f0-9]{64}',identity));created[name]['id']=identity;return identity
for path in [checkout,descriptor,secret_dir,base]:protected(path,True)
for path in [descriptor/'manifest.json',descriptor/'release.env',secret_dir/'recovery.env',secret_dir/'redis.acl']:protected(path)
require(hashlib.sha256((descriptor/'manifest.json').read_bytes()).hexdigest()=='39855f1d5ca9e066e60c001f7127a66121c1c685ba12552b25a1221b111abc9e')
require(checked(['/usr/bin/git','-C',str(checkout),'rev-parse','HEAD'])==revision)
require(not checked(['/usr/bin/git','-C',str(checkout),'status','--porcelain','--untracked-files=all']))
require(not (P('/opt/kairos/runtime')/'active-release').exists())
# Verify every executable source byte before importing release helpers.
for path in (checkout/'scripts').rglob('*'):
    protected(path,path.is_dir())
    require(path.suffix!='.pyc')
    if path.is_file():
        expected=subprocess.run(['/usr/bin/git','-C',str(checkout),'show',revision+':'+path.relative_to(checkout).as_posix()],env=env,capture_output=True,timeout=30)
        require(expected.returncode==0 and expected.stdout==path.read_bytes())
release=module('mount_release','release-manifest.py')
value=json.loads((descriptor/'manifest.json').read_text());release.verify(value,checkout)
images=value['images']
require(value['secrets_dir']==str(secret_dir))
expected_volumes={'redis':{'/data'},'edge':{'/data','/config'},'wordpress':{'/var/www/html'}}
for service in ['redis','edge','wordpress']:
    require(checked(docker+['image','inspect','--format','{{.Id}}',images[service]])==images[service])
    require(set(json.loads(checked(docker+['image','inspect','--format','{{json .Config.Volumes}}',images[service]])) or {})<=expected_volumes[service])
require('userns' not in checked(docker+['info','--format','{{json .SecurityOptions}}']))
redis_live=json.loads(checked(docker+['container','inspect','--format','{"id":{{json .Id}},"image":{{json .Image}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}}}','kairos-redis-1']))
require(redis_live['image']==images['redis'] and redis_live['project']=='kairos' and redis_live['service']=='redis' and re.fullmatch(r'[a-f0-9]{64}',redis_live['id']))
uid=int(checked(docker+['exec',redis_live['id'],'id','-u','redis']))
gid=int(checked(docker+['exec',redis_live['id'],'id','-g','redis']))
require(0<uid<65536 and 0<gid<65536)
report['redis_identity']={'uid':uid,'gid':gid,'image':images['redis']}
lock=os.open('/opt/kairos/runtime/.operation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:
    info=os.fstat(lock);require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    require(not work.exists() and not work.is_symlink());work.mkdir(mode=0o700)
    before='/opt/kairos/runtime/baselines/mount-product-c12e53a-before'
    after='/opt/kairos/runtime/baselines/mount-product-c12e53a-after'
    for path in [P(before),P(after)]:require(not path.exists() and not path.is_symlink())
    require(logged('before',['/bin/bash',str(checkout/'scripts/vps-snapshot.sh'),before])==0)
    manifest=work/'no-changes.json';manifest.write_text(json.dumps({'version':2,'release_commit':revision,'config_changes':[],'network_changes':[],'edge_binding_change':None}))
    try:
        acl=module('mount_redis_acl','redis-acl.py')
        values=acl.read_recovery(secret_dir/'recovery.env')
        require((secret_dir/'redis.acl').read_text()==acl.render(values))
        runtime=secret_dir/'runtime';require(not runtime.exists() and not runtime.is_symlink());runtime.mkdir(mode=0o700)
        fd=os.open(runtime/'redis.acl',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write((secret_dir/'redis.acl').read_bytes());stream.flush();os.fsync(stream.fileno());os.fchown(stream.fileno(),uid,gid);os.fchmod(stream.fileno(),0o400)
        for name in ['infra/caddy/Caddyfile','wordpress/mu-plugins/kairos-admin-gate.php']:
            path=checkout/name;protected(path);path.chmod(0o644)
        report['checks']['code_mount_permissions']='PASS'
        redis=create('redis',images['redis'],['--user',f'{uid}:{gid}','--tmpfs',f'/data:rw,nosuid,size=64m,uid={uid},gid={gid}','--mount',f'type=bind,src={runtime}/redis.acl,dst=/etc/kairos/users.acl,readonly'],['redis-server','--save','','--appendonly','no','--aclfile','/etc/kairos/users.acl','--maxmemory','64mb','--bind','127.0.0.1'])
        checked(docker+['start',redis])
        for attempt in range(20):
            ready=run(docker+['exec',redis,'redis-cli','--raw','PING'])
            if 'NOAUTH' in ready.stdout:break
            time.sleep(1)
        require('NOAUTH' in ready.stdout)
        def commands(lines):
            result=run(docker+['exec','-i',redis,'redis-cli','--raw'],'\n'.join(lines)+'\n')
            require(result.returncode==0);return result.stdout.strip().splitlines()
        rows=commands(['AUTH kairos_cache '+values['KAIROS_REDIS_CACHE_PASSWORD'],'SET kairos:cache:v2:probe verified','GET kairos:cache:v2:probe','SET kairos:broker:v1:forbidden no','CONFIG GET maxmemory','ACL SETUSER escalation on','FLUSHALL'])
        require(rows[:3]==['OK','OK','verified'] and len(rows)==7 and all(row.startswith('NOPERM') for row in rows[3:]))
        for principal,key in acl.PRINCIPALS.items():
            if principal=='kairos_cache':continue
            rows=commands(['AUTH '+principal+' '+values[key],'LPUSH kairos:broker:v1:probe item','RPOP kairos:broker:v1:probe','GET kairos:cache:v2:probe','ACL SETUSER escalation on'])
            require(rows[:3]==['OK','1','item'] and len(rows)==5 and all(row.startswith('NOPERM') for row in rows[3:]))
        require(commands(['AUTH default '+values['REDIS_PASSWORD'],'PING'])==['OK','PONG'])
        report['checks']['real_scoped_redis_acl']='PASS'
        caddy=create('edge',images['edge'],['--user','1000:1000','--tmpfs','/data:rw,nosuid,size=16m,uid=1000,gid=1000','--tmpfs','/config:rw,nosuid,size=16m,uid=1000,gid=1000','--env','KAIROS_PROXY_TOKEN=synthetic-mount-validation-only','--mount',f'type=bind,src={checkout}/infra/caddy/Caddyfile,dst=/etc/caddy/Caddyfile,readonly','--entrypoint','caddy'],['validate','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'])
        require(logged('caddy',docker+['start','-a',caddy])==0)
        require(checked(docker+['inspect','--format','{{.State.Running}}|{{.State.ExitCode}}',caddy])=='false|0')
        report['checks']['caddy_nonroot_config']='PASS'
        wordpress=create('wordpress',images['wordpress'],['--user','33:33','--tmpfs','/var/www/html:rw,nosuid,size=16m,uid=33,gid=33','--mount',f'type=bind,src={checkout}/wordpress/mu-plugins/kairos-admin-gate.php,dst=/gate.php,readonly','--entrypoint','php'],['-l','/gate.php'])
        require(logged('wordpress',docker+['start','-a',wordpress])==0)
        require(checked(docker+['inspect','--format','{{.State.Running}}|{{.State.ExitCode}}',wordpress])=='false|0')
        report['checks']['wordpress_nonroot_plugin']='PASS'
        roles=module('mount_database_roles','database-roles.py')
        sql_plan=roles.plan(roles.recovery_values(secret_dir/'recovery.env'))
        (work/'database-plan.json').write_text(json.dumps(sql_plan,indent=2))
        report['checks']['database_plan']='PREPARED_ONLY'
        report['database_plan_sha256']=sql_plan['plan_sha256']
        require(not checked(['/usr/bin/git','-C',str(checkout),'status','--porcelain','--untracked-files=all']))
    except Exception as error:report['failure']=type(error).__name__+'; protected logs retained'
    finally:
        for name,expected in created.items():
            try:
                ids=checked(docker+['ps','-aq','--no-trunc','--filter','name=^/'+name+'$']).splitlines()
                require(len(ids)<=1)
                if ids:
                    identity=ids[0];require(re.fullmatch(r'[a-f0-9]{64}',identity) and (not expected['id'] or expected['id']==identity))
                    details=json.loads(checked(docker+['container','inspect','--format','{"name":{{json .Name}},"image":{{json .Image}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"run":{{json (index .Config.Labels "com.kairos.mount.probe")}}}',identity]))
                    require(details=={'name':'/'+name,'image':expected['image'],'project':'kairos','run':runid})
                    checked(docker+['rm','-f',identity])
                report['cleanup'][name]='PASS'
            except Exception:report['cleanup'][name]='FAIL'
        report['after_exit']=logged('after',['/bin/bash',str(checkout/'scripts/vps-snapshot.sh'),after,before])
        report['no_touch_exit']=logged('no-touch',['/usr/bin/python3','-I',str(checkout/'scripts/compare-release-snapshots.py'),before,after,'--manifest',str(manifest)]) if report['after_exit']==0 else 125
    required={'code_mount_permissions':'PASS','real_scoped_redis_acl':'PASS','caddy_nonroot_config':'PASS','wordpress_nonroot_plugin':'PASS','database_plan':'PREPARED_ONLY'}
    report['status']='PASS' if not report.get('failure') and report['checks']==required and all(item=='PASS' for item in report['cleanup'].values()) and report['after_exit']==report['no_touch_exit']==0 else 'FAIL'
    (work/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
finally:os.close(lock)
sys.exit(0 if report.get('status')=='PASS' else 1)
PY
