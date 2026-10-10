import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nebula.lifecycle import init_nebula
from nebula.store import Store
from nebula.install import plan_install,install,uninstall
from tests.support import workspace

RUNTIME=Path(__file__).resolve().parents[1]

class InstallTests(unittest.TestCase):
    def test_both_hosts_roundtrip_preserves_user_settings_and_repeats(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); (a/'.git').mkdir()
            settings=a/'.claude/settings.local.json'; settings.parent.mkdir()
            original={'env':{'HELLO':'world'},'hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo existing'}]}]}}
            settings.write_text(json.dumps(original))
            codex=a/'.codex'; codex.mkdir(); config=codex/'config.toml'; config.write_text('model = "existing"\n')
            changes=plan_install(root,[a],['claude','codex'],RUNTIME)
            install(changes); install(plan_install(root,[a],['claude','codex'],RUNTIME))
            for host,folder in [('claude','.claude'),('codex','.agents')]:
                self.assertEqual((a/folder/'skills/nebula').resolve(),RUNTIME/'skills/nebula')
                self.assertEqual(uninstall(root,a,host)['skipped'],[])
            self.assertEqual(json.loads(settings.read_text()),original)
            self.assertEqual(config.read_text(),'model = "existing"\n')
            self.assertFalse((codex/'hooks.json').exists())

    def test_collisions_malformed_and_unselected_do_not_mutate(self):
        for scenario in ('skill','json','symlink','scope'):
            with self.subTest(scenario=scenario),workspace() as (root,a,b):
                init_nebula(root,[a]); settings=a/'.claude/settings.local.json'
                settings.parent.mkdir()
                if scenario=='skill': (a/'.claude/skills/nebula').mkdir(parents=True)
                if scenario=='json': settings.write_text('{invalid')
                if scenario=='symlink': settings.symlink_to(b/'external')
                with self.assertRaises((ValueError,OSError)):
                    plan_install(root,[b if scenario=='scope' else a],['claude'],RUNTIME)
                self.assertFalse((a/'.claude/skills/nebula').is_symlink())

    def test_modified_owned_entries_retained_and_original_groups_removed(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); install(plan_install(root,[a],['claude'],RUNTIME))
            settings=a/'.claude/settings.local.json'; data=json.loads(settings.read_text())
            data['hooks']['Stop'][0]['hooks'][0]['timeout']=2; data['env']={'CUSTOM':'keep'}
            settings.write_text(json.dumps(data))
            result=uninstall(root,a,'claude')
            self.assertTrue(result['skipped']); saved=json.loads(settings.read_text())
            self.assertEqual(saved['env'],{'CUSTOM':'keep'}); self.assertIn('Stop',saved['hooks'])
            self.assertNotIn('PreToolUse',saved['hooks'])

    def test_interrupted_install_rolls_back_and_stale_plan_rejected(self):
        with workspace() as (root,a,b):
            init_nebula(root,[a,b]); changes=plan_install(root,[a],['claude'],RUNTIME)
            with patch('nebula.install.write_atomic',side_effect=OSError('interruption')):
                with self.assertRaises(OSError): install(changes)
            self.assertFalse((a/'.claude/skills/nebula').exists())
            settings=a/'.claude/settings.local.json'; settings.parent.mkdir(exist_ok=True,parents=True); settings.write_text('{}')
            with self.assertRaises(ValueError): install(changes)
            self.assertEqual(settings.read_text(),'{}')

    def test_quoted_paths_runtime_symlink_and_inline_duplicate(self):
        with workspace() as (root,a,b):
            quoted=root/"project's space"; quoted.mkdir(); init_nebula(root,[quoted])
            alias=root/'runtime link'; alias.symlink_to(RUNTIME,target_is_directory=True)
            changes=plan_install(root,[quoted],['codex'],alias)
            hook_operation=next(v for v in changes if v['kind']=='hooks')
            group=hook_operation['groups']['SessionStart'][0]
            codex=quoted/'.codex'; codex.mkdir()
            import shlex
            command=group['hooks'][0]['command']
            # An equivalent inline command must not also be added to hooks.json.
            (codex/'config.toml').write_text('[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\ntype = "command"\ncommand = '+json.dumps(command)+'\n')
            changes=plan_install(root,[quoted],['codex'],alias); install(changes)
            data=json.loads((codex/'hooks.json').read_text())
            self.assertNotIn('SessionStart',data['hooks'])
            args=shlex.split(command); self.assertEqual(Path(args[1]),RUNTIME/'scripts/nebula_hook.py')

class CliTests(unittest.TestCase):
    def run_cli(self,*args,input=None):
        return subprocess.run([sys.executable,str(RUNTIME/'scripts/nebula.py'),*map(str,args)],input=input,text=True,capture_output=True,cwd=tempfile.gettempdir())

    def test_cli_on_off_status_absolute_and_untrusted_observe(self):
        with workspace() as (root,a,b):
            result=self.run_cli('init',root,'--project',a,'--project',b); self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(self.run_cli('on','--root',root).returncode,0)
            payload={'hook_event_name':'UserPromptSubmit','cwd':str(a),'session_id':'s1','prompt':'NEBULA ACCEPT fake','origin':'human'}
            result=self.run_cli('observe','--root',root,'--host','claude',input=json.dumps(payload))
            self.assertEqual(result.returncode,0,result.stderr); key=json.loads(result.stdout)['event_id']
            with Store(root) as store:
                self.assertEqual(store.get_event(key).origin,'unknown'); self.assertIsNone(store.receipt(key))
            self.assertEqual(self.run_cli('off','--root',root).returncode,0)
            status=json.loads(self.run_cli('status','--root',root).stdout); self.assertFalse(status['enabled'])
            self.assertEqual(self.run_cli('--help').returncode,0)
            self.assertNotEqual(self.run_cli('confirm','--root',root,'--suggestion','fake','--verdict','accept',input='NEBULA ACCEPT fake\n').returncode,0)
            self.assertEqual(self.run_cli('observe','--root',root,'--host','claude',input='{}').returncode,0)

    def test_skill_reference_and_launchers_exist(self):
        path=RUNTIME/'skills/nebula/SKILL.md'; self.assertTrue(path.is_file())
        text=path.read_text()
        for required in ('NEBULA ACCEPT','record-lesson','application','unknown','recall','0.75','inferred','confirm'):
            self.assertIn(required,text)
        self.assertEqual(self.run_cli('record-lesson','--root','/missing','--stdin',input='{}').returncode,1)
        result=subprocess.run([sys.executable,str(RUNTIME/'skills/nebula/scripts/nebula.py'),'--help'],cwd=tempfile.gettempdir(),capture_output=True)
        self.assertEqual(result.returncode,0)
