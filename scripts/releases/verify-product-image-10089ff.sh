set -Eeuo pipefail
/usr/bin/python3 -I -B - <<'PY'
import hashlib,importlib.util,json,pathlib,stat,sys,tarfile
sys.dont_write_bytecode=True
root=pathlib.Path('/opt/kairos/runtime/p0/20260918T031838Z-foundations')
archive=root/'source.tar'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='2439ee31d6f146ce804b5fa207c464df01899dd17e630fe37212796de2009c20'
for path in [root,*root.parents]:
 info=path.lstat();assert stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022
work=root/'strict-verification'
work.mkdir(mode=0o700)
with tarfile.open(archive) as items:
 for member in items:
  part=pathlib.PurePosixPath(member.name)
  assert not part.is_absolute() and '..' not in part.parts and (member.isdir() or member.isfile())
  if member.isfile() and part.parts[0]=='scripts':
   target=work.joinpath(*part.parts);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
   with target.open('xb') as stream:stream.write(items.extractfile(member).read())
spec=importlib.util.spec_from_file_location('flashcard_gate',work/'scripts/compare-release-snapshots.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
manifest={'version':2,'release_commit':'10089ff4dae296caf35526bb2c8b51d458cff748','config_changes':[],'network_changes':[],'edge_binding_change':None}
baselines=pathlib.Path('/opt/kairos/runtime/baselines')
result=gate.compare(baselines/'p0p2-candidate-20260918T031838Z-before',baselines/'p0p2-candidate-20260918T031838Z-after',manifest)
(work/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
raise SystemExit(0 if result['result']=='PASS' else 1)
PY
