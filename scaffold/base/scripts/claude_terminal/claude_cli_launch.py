#!/usr/bin/env python3
"""Launch/resume the one user-authorized finite research round, with duplicate guard."""
import contextlib,datetime,fcntl,json,os,subprocess,sys,uuid
from pathlib import Path
sys.dont_write_bytecode = True
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import claude_runner as r

def configure():
 global BASE, PACKET
 path=ROOT/'runs/claude-terminal-active.json'
 if not path.exists():raise ValueError('No active round configured; infrastructure is installed, no research is authorized by installation')
 config=r.load(path)
 relative=r.relative(config['record_directory'])
 if relative.parts[0]!='runs':raise ValueError('Record directory must be below runs/')
 BASE=ROOT/relative
 for part in (BASE,*BASE.parents):
  if part.is_symlink():raise ValueError('Record directory cannot contain symlinks')
 PACKET=r.neutral_path(config['packet'])
 if not BASE.is_dir():raise ValueError('Prepare the local record directory before launch')
 return config

def status():
 enabled=r.integration_enabled(ROOT)
 if not (ROOT/'runs/claude-terminal-active.json').exists():return {'status':'not_configured' if enabled else 'disabled','model_started':False}
 configure()
 r.verify(PACKET)
 return {'enabled':enabled,'supervisor':r.load(BASE/'status.json') if (BASE/'status.json').exists() else {'phase':'not_started'},
         'tasks':r.load(PACKET/'state.json') if (PACKET/'state.json').exists() else {},
         'stop_latched':(PACKET/'STOP.json').exists()}

def launch(resume_stopped=False):
 r.require_integration(ROOT)
 configure()
 with (BASE/'launch.lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  status=BASE/'status.json'
  if status.exists():
   old=r.load(status)
   if old.get('phase')=='running' and r.alive(old.get('pid')):return {'status':'already_running','pid':old['pid']}
   if old.get('phase')=='starting':raise ValueError('Uncertain previous start; inspect receipt before retry')
   if old.get('phase')=='done':return {'status':'already_done'}
  if (PACKET/'STOP.json').exists() and not resume_stopped:raise ValueError('Explicit stop latch requires user resume')
  r.neutral_path(PACKET)
  manifest=r.verify(PACKET)
  release=r.load(PACKET/'release.json')
  if release.get('manifest_sha256')!=r.digest(r.regular(PACKET/'manifest.json')) or release.get('runner_sha256')!=manifest['runner_sha256']:
   raise ValueError('Release does not match active packet')
  if manifest['purpose']=='research' and release.get('research_approved') is not True:raise ValueError('Research not released')
  if len(manifest['tasks'])!=1:raise ValueError('Active launcher expects one research session')
  task=manifest['tasks'][0]
  r.preflight()
  ident=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
  state={'attempt':ident,'phase':'starting','packet':str(PACKET),'resume_stopped':resume_stopped,'requested_model':task['model'],'requested_effort':task['effort'],'at':r.now()}
  r.atomic(status,r.canonical(state))
  env=r.environment();env['PYTHONDONTWRITEBYTECODE']='1'
  # Worker stdout/stderr are not native model streams and contain no prompts.
  log=BASE/(ident+'-supervisor.log')
  with log.open('xb') as out:
   p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',ident],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
  state.update(phase='running',pid=p.pid)
  r.atomic(status,r.canonical(state));r.atomic(BASE/(ident+'-launch.json'),r.canonical(state))
  return {'status':'launched','pid':p.pid,'attempt':ident}

def worker(ident):
 r.require_integration(ROOT)
 configure()
 with (BASE/'launch.lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  state=r.load(BASE/'status.json')
  if state.get('attempt')!=ident or state.get('packet')!=str(PACKET):raise ValueError('Supervisor identity drift')
 # Exact packet is bound by its own launcher and release before any model work.
 log=BASE/(ident+'-runner.log')
 with log.open('xb') as out:
  command=[sys.executable,'-B',str(PACKET/'runner.py'),'run',str(PACKET)]
  if state.get('resume_stopped'):command.append('--resume-stopped')
  p=subprocess.Popen(command,cwd=PACKET,env=r.environment(),stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT)
  code=p.wait()
 with (BASE/'launch.lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  state=r.load(BASE/'status.json')
  if state.get('attempt')!=ident:raise ValueError('Supervisor identity drift')
  tasks=r.load(PACKET/'state.json') if (PACKET/'state.json').exists() else {}
  done=bool(tasks) and all(t.get('status')=='done' for t in tasks.values())
  state.update(phase='done' if code==0 and done else 'paused',exit_code=code,finished_at=r.now(),tasks=tasks,pid=None)
  r.atomic(BASE/'status.json',r.canonical(state));r.atomic(BASE/(ident+'-outcome.json'),r.canonical(state))
 print(json.dumps({'phase':state['phase'],'attempt':ident,'exit_code':code}))

if __name__=='__main__':
 try:
  if len(sys.argv)==3 and sys.argv[1]=='--worker':worker(sys.argv[2])
  elif sys.argv[1:]==['--status']:print(json.dumps(status(),indent=2))
  elif sys.argv[1:]==['--resume-stopped']:print(json.dumps(launch(resume_stopped=True),indent=2))
  elif len(sys.argv)==1:print(json.dumps(launch(),indent=2))
  else:raise ValueError('No arbitrary command or packet accepted')
 except Exception as e:
  print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(1)
