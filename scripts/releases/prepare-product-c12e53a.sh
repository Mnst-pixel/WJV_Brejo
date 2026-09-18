set -Eeuo pipefail
/usr/bin/python3 -I - <<'PY'
import fcntl,hashlib,importlib.util,io,json,os,pathlib,stat,subprocess,sys,tarfile
P=pathlib.Path
revision='c12e53a7416902315391d1b8c0a48603cbb1db6e'
base=P('/opt/kairos/runtime/p0/20260911T042557Z-foundations')
source=base/'source'
bundle=base/'release-source.bundle'
checkout=P('/opt/kairos/releases')/revision
secret_dir=P('/opt/kairos/secrets')/('product-'+revision)
descriptor=P('/opt/kairos/runtime/releases')/('product-'+revision)
work=base/'release-preparation'
env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','PYTHONDONTWRITEBYTECODE':'1','COMPOSE_PROJECT_NAME':'kairos','DOCKER_HOST':'unix:///var/run/docker.sock'}
docker=['/usr/bin/docker','--host','unix:///var/run/docker.sock']
sys.dont_write_bytecode=True
os.environ.clear();os.environ.update(env)
os.umask(0o077)
report={'commit':revision,'checkout':str(checkout),'descriptor':str(descriptor),'secrets_directory':str(secret_dir),'production_deploy':False}
def require(condition):
    if not condition:raise RuntimeError('release preparation invariant failed; details withheld')
def protected(path,*,directory=False):
    info=path.lstat()
    require(not path.is_symlink() and info.st_uid==0 and not info.st_mode&0o022)
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink==1)
    for parent in path.parents:
        info=parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022)
def execute(args,timeout=60):
    result=subprocess.run(args,env=env,capture_output=True,timeout=timeout)
    require(result.returncode==0)
    return result.stdout
def git(*args):return execute(['/usr/bin/git','-C',str(checkout),*args])
def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,checkout/'scripts'/filename)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def logged(label,args):
    with (work/(label+'.log')).open('x') as stream:
        result=subprocess.run(args,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
    return result.returncode
for path in [base,source,P('/opt/kairos/runtime'),P('/opt/kairos/secrets')]:protected(path,directory=True)
protected(bundle)
require(hashlib.sha256(bundle.read_bytes()).hexdigest()=='5aac0767585f2f9857b5398a69dce6583e86a36d0a5b1f90dfb213297126a21a')
protected(base/'source.tar')
archive_bytes=(base/'source.tar').read_bytes()
require(hashlib.sha256(archive_bytes).hexdigest()=='0f147ae327c9c26ccb9e84574f763af448a8148ef0c7ad0c94cb7c9b1d81311a')
require(not work.exists() and not work.is_symlink())
lock=os.open('/opt/kairos/runtime/.operation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:
    info=os.fstat(lock);require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    work.mkdir(mode=0o700)
    # Run evidence tools from a fresh verified archive copy, never a mutable prior extraction.
    verification=work/'verification'
    verification.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
        for item in archive:
            part=pathlib.PurePosixPath(item.name)
            require(not part.is_absolute() and '..' not in part.parts and (item.isfile() or item.isdir()))
            if item.isfile() and part.parts[0]=='scripts':
                target=verification.joinpath(*part.parts)
                target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                with target.open('xb') as stream:stream.write(archive.extractfile(item).read())
    before='/opt/kairos/runtime/baselines/prepare-product-c12e53a-before'
    after='/opt/kairos/runtime/baselines/prepare-product-c12e53a-after'
    for path in [P(before),P(after)]:require(not path.exists() and not path.is_symlink())
    require(logged('before',['/bin/bash',str(verification/'scripts/vps-snapshot.sh'),before])==0)
    manifest=work/'no-changes.json'
    manifest.write_text(json.dumps({'version':2,'release_commit':revision,'config_changes':[],'network_changes':[],'edge_binding_change':None}))
    master=P('/opt/kairos/secrets/.env');protected(master)
    old_master=hashlib.sha256(master.read_bytes()).digest()
    current=P('/opt/kairos/current');protected(current,directory=True)
    require(execute(['/usr/bin/git','-C',str(current),'rev-parse','HEAD']).decode().strip()=='f6ac1c3c510a4f442b9101d599e6598fe8428ca0')
    require(not execute(['/usr/bin/git','-C',str(current),'status','--porcelain']).strip())
    require(not P('/opt/kairos/runtime/active-release').exists() and not P('/opt/kairos/runtime/active-release').is_symlink())
    try:
        for parent in [checkout.parent,descriptor.parent]:
            if not parent.exists():parent.mkdir(mode=0o700)
            protected(parent,directory=True)
        for path in [checkout,secret_dir,descriptor]:require(not path.exists() and not path.is_symlink())
        checkout.mkdir(mode=0o700)
        execute(['/usr/bin/git','init','--template=',str(checkout)])
        git('fetch','--no-tags',str(bundle),'refs/remotes/origin/astra/kairos-p3-p6-produto')
        git('-c','core.hooksPath=/dev/null','checkout','--detach',revision)
        git('remote','add','origin','https://github.com/Mnst-pixel/WJV_Brejo.git')
        require(git('rev-parse','HEAD').decode().strip()==revision)
        require(not git('status','--porcelain','--untracked-files=all').strip())
        require(hashlib.sha256(git('archive','--format=tar',revision)).hexdigest()=='0f147ae327c9c26ccb9e84574f763af448a8148ef0c7ad0c94cb7c9b1d81311a')
        images={
            'api':'sha256:042d06a4cdc875a73150415d97ff34305bfb1b7f772deed9a4a5d1eff1cb2455',
            'parser':'sha256:1e1592bd7fa1ab9183c9ce9bef751d697ac52e906da8a25e65976df073c5168c',
            'web':'sha256:651bf1767d3a6d90924e212bf7579dadd8196e53a2e7c20c42f6a02d7cef6824',
            'edge':'sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648',
            'wordpress':'sha256:8801a1239d7ba9fb340a5fc5ba0bf7f8d3652adbd64893e3fba7992ba618108e',
            'redis':'sha256:9d317178eceac8454a2284a9e6df2466b93c745529947f0cd42a0fa9609d7005',
            'postgres':'sha256:724a4041afdb1750446e3f6b5cfa8f3b0ac5a2cf538ddfa6bfee4f94c2fa85c6',
            'mariadb':'sha256:dd9b303aed4f4890ed09f766d8ca9ddfd176c0c6f6267feff53b3192ec65a979',
            'localai':'sha256:d78cd113b2bc5892d7533c1356e9c9725bb90e86a075356a63730f3d681ce4d7',
            'clamav':'sha256:d06c1d6a451d616e1dd79b42f44c8c8c291bba9cf4e75ebc4d0e43c1c6dd87bb',
            'minio':'sha256:a3167816f450f8aca214fc82a45a86663918ad694ed03b01683771643cdbff72',
        }
        images.update({name:images['api'] for name in ['worker','migrate','beat']})
        image_file=work/'images.json';image_file.write_text(json.dumps(images,indent=2))
        # The source scripts receive only a fixed environment; output remains protected.
        require(logged('secrets',['/usr/bin/python3','-I',str(checkout/'scripts/release-secrets.py'),str(master),str(secret_dir),str(checkout/'config/service-secrets.json')])==0)
        secrets_module=module('release_secrets','release-secrets.py')
        recovery=secrets_module.read_env(secret_dir/'recovery.env')
        specification=json.loads((checkout/'config/service-secrets.json').read_text())
        expected=secrets_module.project(recovery,specification)
        for name,values in expected.items():
            file=secret_dir/(name+'.env');protected(file)
            require(stat.S_IMODE(file.stat().st_mode)==0o600 and secrets_module.read_env(file)==values)
        require(set(path.name for path in secret_dir.iterdir())=={name+'.env' for name in expected}|{'recovery.env'})
        acl=module('release_redis_acl','redis-acl.py')
        acl_values=acl.read_recovery(secret_dir/'recovery.env')
        acl_plan=acl.plan(acl_values)
        acl.write_artifact(secret_dir/'redis.acl',acl_values,acl_plan['acl_sha256'])
        # Runtime ACL ownership is a separate pre-activation gate, not guessed here.
        report['runtime_redis_acl_prepared']=False
        require(logged('descriptor',['/usr/bin/python3','-I',str(checkout/'scripts/release-manifest.py'),str(checkout),str(image_file),str(secret_dir),str(descriptor)])==0)
        compose=module('release_compose','kairos-compose.py')
        command=compose.command(checkout,descriptor,'config',[])
        command[0]='/usr/bin/docker'
        require(command[:3]==docker)
        require(logged('compose-config',command)==0)
        require(hashlib.sha256(master.read_bytes()).digest()==old_master)
        require(not git('status','--porcelain','--untracked-files=all').strip())
        require(not P('/opt/kairos/runtime/active-release').exists())
        report.update(preparation='PASS',image_count=len(images),service_env_count=len(expected),redis_principals=acl_plan['principals'],checkout_clean=True,old_master_unchanged=True,compose_config='PASS',descriptor_sha256=hashlib.sha256((descriptor/'manifest.json').read_bytes()).hexdigest())
    except Exception as error:
        report['failure']=type(error).__name__+'; protected artifacts retained; no activation'
    finally:
        report['after_exit']=logged('after',['/bin/bash',str(verification/'scripts/vps-snapshot.sh'),after,before])
        report['no_touch_exit']=logged('no-touch',['/usr/bin/python3','-I',str(verification/'scripts/compare-release-snapshots.py'),before,after,'--manifest',str(manifest)]) if report['after_exit']==0 else 125
    report['status']='PASS' if report.get('preparation')=='PASS' and report['after_exit']==report['no_touch_exit']==0 else 'FAIL'
    (work/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
finally:os.close(lock)
sys.exit(0 if report.get('status')=='PASS' else 1)
PY
