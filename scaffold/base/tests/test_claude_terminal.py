"""Synthetic tests: no authentication, network or model calls."""
import importlib.util,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
# Isolate the new adapter from existing bound runners during test discovery.
import importlib.util as _importutil
_standard = ('claude_runner', 'claude_runner_support', 'claude_source_capture')
_saved = {name: sys.modules.get(name) for name in _standard}
_scripts = Path(__file__).resolve().parents[1] / 'scripts' / 'claude_terminal'
def _load(name, filename):
    spec = _importutil.spec_from_file_location(name, _scripts / filename)
    module = _importutil.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
try:
    capture = _load(__name__ + '_source', 'claude_source_capture.py')
    sys.modules['claude_source_capture'] = capture
    support = _load(__name__ + '_support', 'claude_runner_support.py')
    sys.modules['claude_runner_support'] = support
    r = _load(__name__ + '_runner', 'claude_runner.py')
    sys.modules['claude_runner'] = r
    launcher = _load(__name__ + '_launcher', 'claude_cli_launch.py')
finally:
    for name, module in _saved.items():
        if module is None: sys.modules.pop(name, None)
        else: sys.modules[name] = module

class RunnerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='abel-runner-test-');self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name).resolve();self.root=self.base/'packet'
  policy=patch.object(r,'LAB_ROOT',self.base);policy.start();self.addCleanup(policy.stop)
  neutral=patch.object(r,'NEUTRAL_ROOT',self.base);neutral.start();self.addCleanup(neutral.stop)
  self.req={'id':'test-round','purpose':'research','tasks':[{'id':'survey','prompt':'Synthetic fixture only.','model':'claude-opus-5-5','effort':'max','public_web':False,'required_outputs':['report.md'],'research_checks':False}]}
  self.request=self.base/'request.json';self.request.write_bytes(r.canonical(self.req))
  r.prepare(self.request,self.root,research_draft=True)
 def test_disabled_integration_blocks_new_prepare_and_direct_run(self):
  (self.base/'config').mkdir()
  (self.base/'config/integrations.json').write_text('{"claude_terminal":{"enabled":false}}')
  with self.assertRaisesRegex(ValueError,'disabled'):r.prepare(self.request,self.base/'another',True)
  self.assertFalse((self.base/'another').exists())
  with self.assertRaisesRegex(ValueError,'disabled'):r.run(self.root)
  # Switching off does not corrupt or rewrite an already sealed packet.
  r.verify(self.root)
 def test_non_neutral_root_refused(self):
  with self.assertRaisesRegex(ValueError,'neutral research root'):r.neutral_path('/Users/example/packet')
 def test_neutral_symlink_refused(self):
  link=self.base/'alias';link.symlink_to(self.base, target_is_directory=True)
  with self.assertRaisesRegex(ValueError,'symlinks'):r.neutral_path(link/'new')
 def test_neutral_root_intermediate_and_packet_reject_foreign_owner(self):
  intermediate=self.base/'intermediate';intermediate.mkdir(mode=0o700)
  packet=intermediate/'packet';r.prepare(self.request,packet,True)
  original=os.stat
  for foreign in (self.base.name,intermediate.name,packet.name):
   def foreign_stat(name,*args,**kwargs):
    value=original(name,*args,**kwargs)
    if name==foreign and kwargs.get('dir_fd') is not None:
     fields=list(value);fields[4]=os.getuid()+1;return os.stat_result(fields)
    return value
   with self.subTest(component=foreign),patch.object(r.os,'stat',side_effect=foreign_stat):
    with self.assertRaisesRegex(ValueError,'owned by the current user'):r.verify(packet)
    with self.assertRaisesRegex(ValueError,'owned by the current user'):r.request_stop(packet)
    with self.assertRaisesRegex(ValueError,'owned by the current user'):r.prepare(self.request,packet/'foreign-new',True)
    with patch.object(r,'preflight',side_effect=AssertionError('must not launch')):
     with self.assertRaisesRegex(ValueError,'owned by the current user'):r.run(packet)
   self.assertFalse((packet/'.lock').exists());self.assertFalse((packet/'STOP.json').exists());self.assertFalse((packet/'foreign-new').exists())
 def test_writable_neutral_components_rejected_before_copy_or_launch(self):
  intermediate=self.base/'unsafe-parent';intermediate.mkdir(mode=0o700)
  for directory in (self.base,intermediate,self.root):
   for permissions in (0o770,0o707):
    with self.subTest(directory=directory.name,mode=oct(permissions)):
     previous=directory.stat().st_mode&0o777;directory.chmod(permissions)
     try:
      target=directory/'new-packet'
      with self.assertRaisesRegex(ValueError,'group/world writable'):r.prepare(self.request,target,True)
      self.assertFalse(target.exists())
      if directory in (self.base,self.root):
       with patch.object(r,'preflight',side_effect=AssertionError('must not launch')):
        with self.assertRaisesRegex(ValueError,'group/world writable'):r.run(self.root)
       self.assertFalse((self.root/'.lock').exists())
     finally:directory.chmod(previous)
 def test_missing_neutral_parents_are_private_without_restricting_system_ancestor(self):
  shared=self.base/'shared';shared.mkdir();shared.chmod(0o777)
  neutral=shared/'neutral';destination=neutral/'first'/'second'/'packet'
  original=os.stat
  def foreign_shared(name,*args,**kwargs):
   value=original(name,*args,**kwargs)
   if name=='shared' and kwargs.get('dir_fd') is not None:
    fields=list(value);fields[4]=os.getuid()+1;return os.stat_result(fields)
   return value
  old_umask=os.umask(0)
  try:
   with patch.object(r,'NEUTRAL_ROOT',neutral),patch.object(r.os,'stat',side_effect=foreign_shared):
    r.prepare(self.request,destination,True);r.verify(destination)
   for directory in (neutral,neutral/'first',neutral/'first/second',destination):
    self.assertEqual(directory.stat().st_mode&0o777,0o700)
    self.assertEqual(directory.stat().st_uid,os.getuid())
  finally:os.umask(old_umask)
  self.assertEqual(shared.stat().st_mode&0o777,0o777)
 def test_neutral_creation_rejects_symlink_or_special_intermediate_without_following(self):
  outside=self.base/'outside';outside.mkdir()
  intermediate=self.base/'unsafe';intermediate.symlink_to(outside,target_is_directory=True)
  for kind in ('symlink','fifo'):
   with self.subTest(kind=kind):
    with self.assertRaises(ValueError):r.prepare(self.request,intermediate/'packet',True)
    self.assertFalse((outside/'packet').exists())
   intermediate.unlink()
   if kind=='symlink':os.mkfifo(intermediate)
 def test_packet_lock_cannot_write_through_a_symlink(self):
  outside=self.base/'unrelated-lock';outside.write_bytes(b'untouched')
  (self.root/'.lock').symlink_to(outside)
  with self.assertRaises(OSError):
   with r.lock(self.root):self.fail('must not acquire unsafe lock')
  self.assertEqual(outside.read_bytes(),b'untouched')
 def test_exported_runner_does_not_read_unrelated_shared_integration_setting(self):
  shared=self.base/'shared-export';packet=shared/'neutral'/'packet';packet.mkdir(parents=True)
  for name in ('runner.py','claude_runner_support.py','claude_source_capture.py'):
   source=_scripts/('claude_runner.py' if name=='runner.py' else name);shutil.copy2(source,packet/name)
  configuration=shared/'config';configuration.mkdir();switch=configuration/'integrations.json'
  for value in ('{"claude_terminal":{"enabled":false}}','malformed unrelated config',None):
   with self.subTest(value=value):
    if value is None:
     switch.unlink();(shared/'LAB_PROFILE.json').write_text('{"integrations":{}}')
    else:switch.write_text(value)
    result=subprocess.run([sys.executable,'-B',str(packet/'runner.py'),'integration-status'],text=True,capture_output=True,timeout=10)
    self.assertEqual(result.returncode,0,result.stderr)
    self.assertEqual(json.loads(result.stdout),{'enabled':True,'model_started':False})
 def test_personal_paths_blocked(self):
  for value in ('/Users/example/report.md','/home/example/report.md','file:///tmp/a'):
   self.assertTrue(support.relay_screen(value.encode(),'report.md'))
  self.assertFalse(support.relay_screen(b'input/report.md','report.md'))
  self.assertFalse(support.relay_screen(b'https://example.org/home/author/paper','paper.txt'))
 def test_private_prompt_rejected_before_materialization(self):
  self.req['tasks'][0]['prompt']='Read /Users/example/private.md'
  self.request.write_bytes(r.canonical(self.req)); dest=self.base/'new'
  with self.assertRaisesRegex(ValueError,'privacy review'):r.prepare(self.request,dest,True)
  self.assertFalse(dest.exists())
 def test_essay_fields_refused(self):
  self.req['tasks'][0]['manuscripts']=['essay.md'];self.request.write_bytes(r.canonical(self.req))
  with self.assertRaisesRegex(ValueError,'Essay-specific'):r.prepare(self.request,self.base/'new',True)
 def test_multiple_sessions_require_reason(self):
  self.req['tasks'].append({**self.req['tasks'][0],'id':'second'});self.request.write_bytes(r.canonical(self.req))
  with self.assertRaisesRegex(ValueError,'rationale'):r.prepare(self.request,self.base/'new',True)
 def test_interrupted_stage_does_not_publish_partial_work(self):
  t=self.req['tasks'][0];states={'survey':{'status':'pending'}}
  with patch.object(r,'inventory',side_effect=r.FilesChanging('fixture')):
   with self.assertRaises(r.FilesChanging):r.stage(self.root,t,states)
  self.assertFalse((self.root/'work/survey').exists())
  self.assertTrue((r.stage(self.root,t,states)/'input/task.md').exists())
 def release(self):
  m=r.verify(self.root)
  v={'files':{**m['input_hashes'],**m['support_hashes'],'manifest.json':r.digest(r.regular(self.root/'manifest.json')),'runner.py':m['runner_sha256']},'privacy_reviewed':True,'reviewer':'synthetic-test','notes':'Synthetic only','live_test_approved':True,'approval_source':'synthetic-test','subscription_auth_verified':True,'research_approved':True,'technical_acceptance':'synthetic','rules_checked':True,'archive_approval_event':'synthetic'}
  p=self.base/'review.json';p.write_bytes(r.canonical(v));r.release(self.root,p)
 def test_environment_excludes_credentials(self):
  with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'fake','ANTHROPIC_BASE_URL':'fake','CLAUDE_CODE_USE_BEDROCK':'1'}):
   env=r.environment();self.assertNotIn('ANTHROPIC_API_KEY',env);self.assertNotIn('ANTHROPIC_BASE_URL',env)
 def test_explicit_model_max_and_restrictions(self):
  args=r.arguments('claude',self.req['tasks'][0],{'session_id':'id'})
  self.assertEqual(args[args.index('--model')+1],'claude-opus-5-5');self.assertEqual(args[args.index('--effort')+1],'max')
  self.assertIn('--restricted',args);self.assertIn('--safe-mode',args);self.assertNotIn('Bash',args[args.index('--tools')+1]);self.assertNotIn('--dangerously-skip-permissions',args)
 def test_resume_identity(self):
  a=r.arguments('claude',self.req['tasks'][0],{'session_id':'same','session_observed':True});self.assertIn('--resume',a);self.assertEqual(a[-1],'same')
 def test_input_drift_rejected(self):
  (self.root/'inputs/survey/task.md').write_text('changed')
  with self.assertRaises(ValueError):r.verify(self.root)
 def test_symlink_rejected(self):
  p=self.base/'link';p.symlink_to(self.request)
  with self.assertRaises(ValueError):r.regular(p)
 def test_hash_bound_release(self):
  self.release();self.assertTrue((self.root/'release.json').exists())
 def test_no_overwrite_packet(self):
  with self.assertRaises(ValueError):r.prepare(self.request,self.root,True)
 def test_hidden_reasoning_not_persisted(self):
  v=r.visible({'type':'assistant','message':{'model':'claude-opus-5-5','content':[{'type':'thinking','thinking':'SECRET'},{'type':'text','text':'visible'},{'type':'tool_use','name':'Read','input':{'content':'SECRET'}}]}})
  self.assertNotIn('SECRET',json.dumps(v));self.assertEqual(v['text'],['visible'])
 def test_private_source_blocked(self):
  for url in ('file:///etc/passwd','http://example.com','https://127.0.0.1/private','https://user:password@example.com'):
   with self.assertRaises(ValueError):capture.public_url(url)
 def test_source_extraction(self):
  out,_,_=capture.extract(b'<html><head>hidden</head><p>Evidence</p><script>hidden</script></html>','text/html')
  self.assertIn(b'Evidence',out);self.assertNotIn(b'hidden',out)
 def test_native_configuration_rejects_wrong_effort(self):
  self.release();states={'survey':{'status':'pending','session_id':'test'}};work=r.stage(self.root,self.req['tasks'][0],states)
  (work/'output/report.md').write_text('fixture');(work/'output/source-status.json').write_text('{"sources":[{"url":"https://example.com","coverage":"unavailable","note":"fixture"}]}')
  t={**self.req['tasks'][0],'research_checks':True};v=support.validate(r,self.root,t,states['survey'],{'observations':[{'model':'claude-opus-5-5','effort':'xhigh'}]})
  self.assertIn('native_configuration_unverified_or_changed',v['errors'])
 def check_sources(self, value, artifact=None):
  states={'survey':{'status':'pending','session_id':'test'}}
  work=r.stage(self.root,self.req['tasks'][0],states)
  (work/'output/report.md').write_text('Synthetic self-contained calculation')
  (work/'output/source-status.json').write_text(json.dumps(value))
  if artifact is not None:(work/'output/captured.txt').write_text(artifact)
  return support.validate(r,self.root,{**self.req['tasks'][0],'research_checks':True},states['survey'],{'observations':[{'model':'claude-opus-5-5','effort':'max'}]})
 def test_self_contained_task_needs_no_invented_citation(self):
  result=self.check_sources({'sources':[],'no_external_sources_reason':'Self-contained calculation using the supplied definitions.'})
  self.assertTrue(result['passed'],result)
 def test_empty_sources_explain_the_actual_scope(self):
  for reason in (None,'','   ',[],True,'x'*4097):
   with self.subTest(reason=str(reason)[:20]):
    self.assertIn('source_status_missing_or_invalid',self.check_sources({'sources':[],'no_external_sources_reason':reason})['errors'])
 def test_malformed_source_status_is_a_validation_failure(self):
  for value in (None,[],42,{'sources':None},{'sources':[None]},{'sources':[[]]},{'sources':[{'url':'https://example.org','coverage':[],'note':'fixture'}]}):
   with self.subTest(value=value):
    self.assertIn('source_status_missing_or_invalid',self.check_sources(value)['errors'])
 def test_existing_source_rows_still_work(self):
  result=self.check_sources({'sources':[{'url':'https://example.org','coverage':'unavailable','note':'Not retrieved; no source-backed claim.'}]})
  self.assertTrue(result['passed'],result)
 def test_claimed_full_source_requires_captured_bytes(self):
  status={'sources':[{'url':'https://example.org','coverage':'full','note':'Synthetic fixture','artifact':'output/captured.txt'}]}
  self.assertFalse(self.check_sources(status)['passed'])
  self.assertTrue(self.check_sources(status,'captured bytes')['passed'])
 def test_malformed_and_changed_capture_receipts_are_rejected(self):
  self.check_sources({'sources':[],'no_external_sources_reason':'Synthetic task'})
  sources=self.root/'work/survey/output/sources';sources.mkdir()
  (sources/'receipt.json').write_text('[]')
  v=self.check_sources({'sources':[],'no_external_sources_reason':'Synthetic task'})
  self.assertIn('invalid_source_receipt:receipt.json',v['errors'])
  (sources/'captured.txt').write_text('changed')
  (sources/'receipt.json').write_text(json.dumps({'text':'captured.txt','text_sha256':r.digest(b'original')}))
  v=self.check_sources({'sources':[],'no_external_sources_reason':'Synthetic task'})
  self.assertIn('source_changed:receipt.json',v['errors'])
 def fake_run(self,quota=False,special=False):
  self.release();fake=self.base/'fake.py'
  fake.write_text('''import sys,json
from pathlib import Path
sid=sys.argv[1];sys.stdin.read()
print(json.dumps({'type':'system','subtype':'init','session_id':sid,'model':'claude-opus-5-5'}),flush=True)
Path('output/report.md').write_text('Preserved partial or complete result')
'''+("import os;os.mkfifo('output/unexpected-pipe')\n" if special else '')+("print(json.dumps({'type':'rate_limit_event','rate_limit_info':{'status':'rejected','resetsAt':1999999999}}),flush=True)\nprint(json.dumps({'type':'result','subtype':'error_during_execution','is_error':True,'result':'usage limit reached','session_id':sid}),flush=True)" if quota else "print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':'done','session_id':sid}),flush=True)"))
  args=lambda exe,t,s:[sys.executable,str(fake),s['session_id']]
  with patch.object(r,'preflight',return_value='fake'),patch.object(r,'arguments',side_effect=args),patch.object(support,'native_observations',return_value={'observations':[]}):
   result=r.run(self.root)
  return result,r.load(self.root/'state.json')['survey']
 def test_success_archives_output(self):
  res,state=self.fake_run();self.assertEqual(res['status'],'done');self.assertIn('report.md',state['outputs']);self.assertTrue(state['session_observed'])
 def test_preparation_and_fake_run_work_with_group_writable_default_umask(self):
  old_umask=os.umask(0o002)
  try:
   self.root=self.base/'nested'/'umask-packet'
   r.prepare(self.request,self.root,research_draft=True)
   result,state=self.fake_run()
   self.assertEqual(result['status'],'done');self.assertTrue(state['session_observed'])
   for directory in (self.root.parent,self.root,self.root/'inputs',self.root/'inputs/survey',
                     self.root/'work',self.root/'work/survey',self.root/'work/survey/input',
                     self.root/'work/survey/output',self.root/'staging',self.root/'records',
                     self.root/'bindings',self.root/'objects',self.root/'snapshots'):
    with self.subTest(directory=directory):self.assertEqual(directory.stat().st_mode&0o777,0o700)
  finally:os.umask(old_umask)
 def test_collect_preserves_hashes_and_refuses_overwrite(self):
  self.fake_run();destination=self.base/'quarantine';r.collect(self.root,destination)
  receipt=r.load(destination/'collection.json')
  for name,key in receipt['files'].items():self.assertEqual(r.digest(r.regular(destination/name)),key)
  self.assertEqual(receipt['canonical_import'],'pending')
  with self.assertRaises(ValueError):r.collect(self.root,destination)
 def test_collect_resolves_harmless_parent_alias_and_preserves_exact_bytes(self):
  self.fake_run();physical=self.base/'physical-output';physical.mkdir()
  alias=self.base/'output-alias';alias.symlink_to(physical,target_is_directory=True)
  result=r.collect(self.root,alias/'new-parent'/'collected')
  destination=physical/'new-parent/collected'
  self.assertEqual(result['collection'],str(destination))
  receipt=r.load(destination/'collection.json')
  self.assertEqual(result['collection_sha256'],r.digest(r.regular(destination/'collection.json')))
  for name,key in receipt['files'].items():self.assertEqual(r.digest(r.regular(destination/name)),key)
  self.assertEqual((destination/'runner.py').read_bytes(),(self.root/'runner.py').read_bytes())
  before={str(p.relative_to(destination)):p.read_bytes() for p in destination.rglob('*') if p.is_file()}
  with self.assertRaisesRegex(ValueError,'must be new'):r.collect(self.root,alias/'new-parent'/'collected')
  self.assertEqual({str(p.relative_to(destination)):p.read_bytes() for p in destination.rglob('*') if p.is_file()},before)
 def test_collect_rejects_parent_alias_into_packet_before_creating_destination(self):
  alias=self.base/'packet-alias';alias.symlink_to(self.root,target_is_directory=True)
  for destination in (alias/'collected',alias/'new-parent'/'collected'):
   with self.subTest(destination=destination):
    with self.assertRaisesRegex(ValueError,'outside packet'):r.collect(self.root,destination)
  self.assertFalse((self.root/'collected').exists());self.assertFalse((self.root/'new-parent').exists())
 def test_collect_preserves_existing_and_dangling_leaf_under_parent_alias(self):
  physical=self.base/'physical-output';physical.mkdir()
  alias=self.base/'output-alias';alias.symlink_to(physical,target_is_directory=True)
  (physical/'existing-file').write_bytes(b'original');(physical/'existing-dir').mkdir()
  absent=self.base/'must-stay-absent';(physical/'dangling').symlink_to(absent,target_is_directory=True)
  for leaf in ('existing-file','existing-dir','dangling'):
   with self.subTest(leaf=leaf):
    with self.assertRaisesRegex(ValueError,'must be new'):r.collect(self.root,alias/leaf)
  self.assertEqual((physical/'existing-file').read_bytes(),b'original')
  self.assertEqual(list((physical/'existing-dir').iterdir()),[])
  self.assertTrue((physical/'dangling').is_symlink());self.assertFalse(absent.exists())
 def test_collect_uses_resolved_destination_when_parent_alias_is_retargeted(self):
  physical=self.base/'physical-output';physical.mkdir()
  unrelated=self.base/'unrelated-output';unrelated.mkdir();(unrelated/'sentinel').write_bytes(b'untouched')
  alias=self.base/'output-alias';alias.symlink_to(physical,target_is_directory=True)
  original=Path.mkdir;retargeted=[]
  def mkdir(path,*args,**kwargs):
   if path==physical/'collected' and not retargeted:
    alias.unlink();alias.symlink_to(unrelated,target_is_directory=True);retargeted.append(True)
   return original(path,*args,**kwargs)
  with patch.object(Path,'mkdir',mkdir):result=r.collect(self.root,alias/'collected')
  self.assertEqual(retargeted,[True]);self.assertEqual(result['collection'],str(physical/'collected'))
  self.assertTrue((physical/'collected/collection.json').is_file())
  self.assertEqual((unrelated/'sentinel').read_bytes(),b'untouched')
  self.assertFalse((unrelated/'collected').exists())
 def test_unreleased_packet_cannot_dispatch(self):
  with patch.object(r,'preflight',side_effect=AssertionError('must not launch')):
   with self.assertRaises(FileNotFoundError):r.run(self.root)
 def test_harness_failure_records_paused_and_path(self):
  with self.assertRaisesRegex(ValueError,'unexpected-pipe'):self.fake_run(special=True)
  s=r.load(self.root/'state.json')['survey'];self.assertEqual(s['status'],'paused');self.assertEqual(s['reason'],'harness_error');self.assertIsNone(s['pid']);self.assertIn('unexpected-pipe',s['harness_error'])
 def test_quota_preserves_session_and_partial(self):
  res,state=self.fake_run(True);self.assertEqual(state['reason'],'quota');self.assertEqual(state['quota_notice']['resetsAt'],1999999999);self.assertIn('report.md',state['outputs']);self.assertTrue(state['session_observed'])
 def test_stop_latch_blocks_dispatch(self):
  self.release();r.atomic(self.root/'STOP.json',r.canonical({'reason':'test'}))
  with patch.object(r,'preflight',side_effect=AssertionError('must not launch')):self.assertEqual(r.run(self.root)['reason'],'batch_stop_latched')
 def stop_cli(self,target):
  # Only the fixed neutral root is substituted; parse and execute the real CLI
  # in a fresh process, without a provider or any live packet.
  code='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import claude_runner as runner
runner.NEUTRAL_ROOT=Path(sys.argv[2])
runner.LAB_ROOT=Path(sys.argv[2])
sys.argv=['claude_runner.py','stop',sys.argv[3]]
raise SystemExit(runner.main())
'''
  return subprocess.run([sys.executable,'-B','-c',code,str(_scripts),str(self.base),str(target)],text=True,capture_output=True,timeout=10)
 def test_stop_cli_rejects_missing_unrelated_and_symlink_targets(self):
  sentinel=b'UNRELATED ORIGINAL\n'
  unrelated=self.base/'unrelated';unrelated.mkdir();(unrelated/'STOP.json').write_bytes(sentinel)
  alias=self.base/'alias';alias.symlink_to(unrelated,target_is_directory=True)
  missing=self.base/'missing'/'packet'
  with tempfile.TemporaryDirectory(prefix='outside-neutral-') as outside:
   for target in (missing,unrelated,alias,Path(outside)):
    with self.subTest(target=target):
     result=self.stop_cli(target);self.assertEqual(result.returncode,1,result.stdout)
     self.assertNotIn('Traceback',result.stderr)
     self.assertEqual((unrelated/'STOP.json').read_bytes(),sentinel)
   self.assertFalse((Path(outside)/'STOP.json').exists())
  self.assertFalse((self.base/'missing').exists())
 def test_stop_cli_rejects_invalid_and_oversized_manifest_without_writes(self):
  sentinel=b'previous latch\n';(self.root/'STOP.json').write_bytes(sentinel)
  minimal={'protocol':r.PROTOCOL,'id':'test-round','purpose':'research'}
  values=[b'{bad',b'[]',r.canonical({**minimal,'protocol':'unknown'}),
          r.canonical({**minimal,'id':[]}),r.canonical({**minimal,'purpose':[]}),
          b' '*(r.STOP_MANIFEST_MAX_BYTES+1)]
  for value in values:
   with self.subTest(length=len(value)):
    (self.root/'manifest.json').write_bytes(value)
    result=self.stop_cli(self.root);self.assertEqual(result.returncode,1,result.stdout)
    self.assertNotIn('Traceback',result.stderr)
    self.assertEqual((self.root/'STOP.json').read_bytes(),sentinel)
    self.assertEqual(list(self.root.glob('.tmp-stop-*')),[])
 def test_stop_cli_rejects_symlink_and_fifo_manifest(self):
  manifest=self.root/'manifest.json';saved=self.base/'saved-manifest.json'
  manifest.rename(saved);manifest.symlink_to(saved)
  result=self.stop_cli(self.root);self.assertEqual(result.returncode,1,result.stdout)
  self.assertFalse((self.root/'STOP.json').exists())
  manifest.unlink();os.mkfifo(manifest)
  result=self.stop_cli(self.root);self.assertEqual(result.returncode,1,result.stdout)
  self.assertIn('regular packet manifest',result.stderr)
  self.assertFalse((self.root/'STOP.json').exists())
 def test_stop_cli_preserves_symlinked_stop_destination(self):
  target=self.base/'unrelated-stop';target.write_bytes(b'original')
  (self.root/'STOP.json').symlink_to(target)
  result=self.stop_cli(self.root);self.assertEqual(result.returncode,1,result.stdout)
  self.assertEqual(target.read_bytes(),b'original');self.assertTrue((self.root/'STOP.json').is_symlink())
 def test_stop_cli_works_with_live_lock_input_drift_and_disabled_integration(self):
  (self.root/'inputs/survey/task.md').write_text('changed after start')
  (self.base/'config').mkdir();(self.base/'config/integrations.json').write_text('{"claude_terminal":{"enabled":false}}')
  with r.lock(self.root):
   result=self.stop_cli(self.root)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(json.loads(result.stdout),{'stop_requested':True})
  self.assertEqual(r.load(self.root/'STOP.json')['reason'],'explicit_stop')
  self.assertFalse((self.root/'state.json').exists())
 def test_runner_command_without_bytecode_flags_keeps_tree_clean(self):
  scripts=self.base/'ordinary-cli'/'scripts'/'claude_terminal';scripts.mkdir(parents=True)
  for source in _scripts.glob('*.py'):shutil.copy2(source,scripts/source.name)
  env=dict(os.environ);env.pop('PYTHONDONTWRITEBYTECODE',None);env.pop('PYTHONPYCACHEPREFIX',None)
  result=subprocess.run([sys.executable,str(scripts/'claude_runner.py'),'integration-status'],env=env,text=True,capture_output=True,timeout=10)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertFalse(json.loads(result.stdout)['model_started'])
  self.assertEqual(list(scripts.rglob('__pycache__')),[])
 def test_disappearing_entry_is_retried(self):
  folder=self.base/'changing';folder.mkdir();f=folder/'temporary';f.write_text('partial')
  original=Path.rglob;calls=0
  def listing(p,pattern):
   nonlocal calls
   if p==folder and calls==0:
    calls+=1;f.unlink();return iter([f])
   return original(p,pattern)
  with patch.object(Path,'rglob',listing):self.assertEqual(r.inventory(folder),{})
 def test_old_error_reproduced_by_disappearing_file(self):
  f=self.base/'vanishing';f.write_text('ordinary');listed=[f];f.unlink()
  with self.assertRaisesRegex(ValueError,'Special file in packet'):
   for p in listed:
    if p.is_file():pass
    elif not p.is_dir():raise ValueError('Special file in packet')
 def test_live_snapshot_keeps_last_good_version(self):
  work=self.root/'work/survey/output';work.mkdir(parents=True);(work/'report.md').write_text('complete bytes')
  old=r.snapshot(self.root,'survey')
  with patch.object(r,'tree_bytes',side_effect=r.FilesChanging('test transient')):
   self.assertEqual(r.snapshot(self.root,'survey',live=True),old)
   with self.assertRaises(r.FilesChanging):r.snapshot(self.root,'survey')
  self.assertEqual(r.load(self.root/'snapshots/survey.json'),old)
 def test_real_special_file_is_not_ignored(self):
  folder=self.base/'fifo-test';folder.mkdir();f=folder/'pipe';os.mkfifo(f)
  with self.assertRaisesRegex(ValueError,'Special file in packet: .*pipe'):r.inventory(folder)
 def test_snapshot_stores_exact_captured_bytes(self):
  work=self.root/'work/survey/output';work.mkdir(parents=True);(work/'report.md').write_bytes(b'version-one')
  snapshot=r.snapshot(self.root,'survey');key=snapshot['report.md']
  self.assertEqual(key,r.digest(b'version-one'));self.assertEqual((self.root/'objects'/key).read_bytes(),b'version-one')

if __name__=='__main__':unittest.main()
