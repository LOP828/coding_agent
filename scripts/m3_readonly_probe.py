"""No-model, disposable read-only sandbox checks; failures never count as enforcement."""
import argparse
from pathlib import Path
import platform
import subprocess
import uuid
from coding_agent.codex_executor import configuration_identity, sandbox_overrides, policy_template as executor_template
from coding_agent.m0 import PolicyError
from coding_agent.python_environment import clean_environment
from coding_agent.readonly_ai import PROFILE, policy_template, readonly_overrides
from coding_agent.verification import run_captured, write_json
from coding_agent.workspace import snapshot


def probe(run_root, controller):
    run_root, controller = run_root.resolve(), controller.resolve()
    if run_root.is_relative_to(controller):
        raise PolicyError('PROBE_MUST_BE_OUTSIDE_CONTROLLER')
    root = run_root / ('readonly-' + uuid.uuid4().hex[:12]); state = root / 'state'
    state.mkdir(parents=True); (state / 'sentinel.txt').write_text('private', encoding='utf-8')
    evidence = state / 'evidence'
    version = subprocess.run(['codex', '--version'], capture_output=True, check=True).stdout.decode('utf-8').strip()
    cases = {
        'read_allowed': "Path('existing.txt').read_text(encoding='utf-8')",
        'write_existing': "Path('existing.txt').write_text('changed',encoding='utf-8')",
        'new_file': "Path('new.txt').write_text('changed',encoding='utf-8')",
        'delete': "Path('existing.txt').unlink()",
        'rename': "Path('existing.txt').rename('renamed.txt')",
        'replace': "Path('other.txt').replace('existing.txt')",
        'link_write': "Path('link.txt').write_text('changed',encoding='utf-8')",
        'child_write': "subprocess.run(['/usr/bin/python3','-I','-B','-c',\"from pathlib import Path; Path('child.txt').write_text('changed',encoding='utf-8')\"],check=True)",
        'read_state': f"Path({str(state / 'sentinel.txt')!r}).read_text(encoding='utf-8')",
        'write_state': f"Path({str(state / 'sentinel.txt')!r}).write_text('changed',encoding='utf-8')",
        'read_controller': f"Path({str(controller / 'docs/M3/Coding_Agent_M3_Codex_Task.md')!r}).read_text(encoding='utf-8')",
    }
    cases['executor_allowed_write'] = cases['write_existing']
    cases['executor_state_read'] = cases['read_state']
    cases['executor_state_write'] = cases['write_state']
    rows = []
    for name, expression in cases.items():
        project = root / name; project.mkdir()
        for file in ('existing.txt','other.txt'):
            (project / file).write_text('baseline',encoding='utf-8')
        (project / 'link.txt').symlink_to('existing.txt')
        before = snapshot(project)
        code = "from pathlib import Path\nimport subprocess\nprint('PROBE_STARTED',flush=True)\n" + expression + "\nprint('PROBE_COMPLETED',flush=True)\n"
        is_executor = name.startswith('executor_')
        overrides = (sandbox_overrides(project,controller,evidence,(state,)) if is_executor else
                     readonly_overrides(project,controller,state))
        profile = 'm2_provider' if is_executor else PROFILE
        command = ['codex','--no-daemon','sandbox','-C',str(project),'-P',profile,
                   *overrides,'--','/usr/bin/python3','-I','-B','-c',code]
        result = run_captured(command,cwd=project,env=clean_environment(),evidence=evidence/name,
                              prefix='probe',timeout=30)
        out = Path(result['stdout']).read_text(encoding='utf-8',errors='replace')
        err = Path(result['stderr']).read_text(encoding='utf-8',errors='replace')
        started = 'PROBE_STARTED' in out; completed = 'PROBE_COMPLETED' in out
        after = snapshot(project)
        denied = started and not completed and result['exit_code'] != 0 and any(t in err for t in ('PermissionError','Read-only file system','Operation not permitted','Permission denied'))
        row = {'case':name,'execution':result,'started':started,'completed':completed,'before':before,'after':after,
               'classification':'POSITIVE_WRITE' if name=='executor_allowed_write' and completed else
               'POSITIVE_READ' if name=='read_allowed' and completed else
               'SANDBOX_DENIED' if denied and before==after else 'UNVERIFIED',
               'configuration_identity':configuration_identity(project)}
        write_json(evidence/name/'result.json',row); rows.append(row)
    proof = {'codex_version':version,'platform':platform.system(),'policy_template':policy_template(),
             'configuration_identity':rows[0]['configuration_identity'],'model_calls':0,
             'usable_for_planning':all(r['classification']==('POSITIVE_READ' if r['case']=='read_allowed' else 'SANDBOX_DENIED') for r in rows if not r['case'].startswith('executor_'))
              and len({str(r['configuration_identity']) for r in rows})==1,
             'state_sentinel_unchanged':(state/'sentinel.txt').read_text(encoding='utf-8')=='private',
             'rows':[{k:v for k,v in r.items() if k not in ('before','after','configuration_identity')} for r in rows]}
    proof['usable_for_planning'] &= proof['state_sentinel_unchanged']
    executor_rows = [r for r in rows if r['case'].startswith('executor_')]
    write_json(evidence/'executor-proof.json', {
        'codex_version':version,'platform':platform.system(),'policy_template':executor_template((state,)),
        'configuration_identity':rows[0]['configuration_identity'],'matrix_complete':True,
        'usable_for_executor':all(r['classification']==('POSITIVE_WRITE' if r['case']=='executor_allowed_write' else 'SANDBOX_DENIED') for r in executor_rows),
        'model_calls':0,'scope':'M2 sandbox plus external M3 state access denial; supplements M2 full matrix',
        'rows':executor_rows})
    write_json(evidence/'readonly-proof.json',proof)
    return evidence/'readonly-proof.json'

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-root',type=Path,required=True);p.add_argument('--controller',type=Path,required=True)
    a=p.parse_args();print(probe(a.run_root,a.controller))
