"""Explicit M3 operator commands. Preparation and scripted demo do not invoke models."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from .findings import ingest, parse_message
from .m0 import PolicyError, approval_payload_sha256, read_json
from .m2_run import create_demo
from .map_controller import MapController
from .map_permissions import protect_draft
from .map_report import render
from .map_store import MapStore
from .readonly_ai import ReadOnlyAI, planning_prompt
from .runner import Runner
from .task_map import digest, validate_proposal
from .verification import write_json
from .workspace import snapshot


def seed_node(node_id, parent, kind, refs):
    return dict(id=node_id, parent_id=parent, title=node_id, type=kind,
                requirement_refs=refs, origin='EXPLICIT', derivation_reason='')


def scripted_demo(run_root, controller):
    run_root, controller = Path(run_root).resolve(), Path(controller).resolve()
    if run_root.is_relative_to(controller):
        raise PolicyError('DEMO_MUST_BE_OUTSIDE_CONTROLLER')
    base = run_root / 'script-demo'
    base.mkdir(parents=True, exist_ok=False)
    store = MapStore(base/'state', fixture_mode=True)
    source = read_json(controller/'tests/data/m2/fixtures/source_requirements.json')
    source['requirements'] += read_json(controller/'tests/data/m3/source_requirements.json')['requirements']
    store.initialize('无模型脚本演示（合成夹具）', source)
    control = MapController(store, controller)
    for node_id, parent, kind in [('root',None,'STAGE'),('first','root','ATOMIC'),('second','root','ATOMIC')]:
        control.mk('create', basis='MK_SCRIPTED_FIXTURE', node=seed_node(node_id,parent,kind,['R-001']))
        control.mk('transition', basis='MK_SCRIPTED_FIXTURE', node_id=node_id,target='READY')
    control.mk('switch_focus', basis='MK_SCRIPTED_FIXTURE', node_id='root')
    trusted = base/'trusted'
    shutil.copytree(controller/'tests/data/m2', trusted)
    card = read_json(trusted/'fixtures/01_correct/atomic_task.json')
    card['acceptance_review']['status'] = 'PENDING'
    card = protect_draft(card)
    card['acceptance_review']['status'] = 'APPROVED'
    records = read_json(trusted/'fixtures/trusted_review_records.json')
    card['acceptance_review']['approved_payload_sha256'] = approval_payload_sha256(card,source)
    for row in records['review_records']:
        if row['approval_ref'] == card['acceptance_review']['approval_ref']:
            row['approved_payload_sha256'] = card['acceptance_review']['approved_payload_sha256']
    runner = Runner(trusted,source,records,base/'runner',fixture_mode=True)
    message = json.dumps(read_json(controller/'tests/data/m3/valid_finding_message.json'),ensure_ascii=False).encode('utf-8')
    def executor_factory(number,prompt):
        def executor(repo):
            shutil.copyfile(controller/'tests/data/m0/example_code/01_correct/config_loader.py',repo/'config_loader.py')
        executor.findings_message = message
        return executor
    result = control.execute('first',card,runner,lambda n:create_demo(base/f'attempt-{n}',trusted/'demo_starter'),
                             executor_factory,basis='MK_SCRIPTED_FIXTURE_START')
    # An AI output attempting to promote a finding is only a malformed finding message.
    try:
        ingest(store,b'{"operation":"promote_finding","actor":"MK"}',node_id='first',run_id='demo',submission_id='unauthorized-promotion')
    except Exception:
        pass
    # A generic state change cannot dispatch a sibling; only the explicit bound run entrypoint can.
    try:
        control.mk('transition',basis='REJECT_GENERIC_EXECUTION_REQUEST',node_id='second',target='RUNNING')
    except PolicyError as error:
        sibling_rejection = str(error)
    else:
        raise AssertionError('sibling request unexpectedly accepted')
    status = render(store)
    (base/'status_report.md').write_text(status,encoding='utf-8')
    summary = {'model_calls':0,'workflow':result,'state':store.read(),'sibling_request_rejected':sibling_rejection,
               'status_report':str(base/'status_report.md'),'source_kind_notice':'M2 synthetic fixture plus unchanged MK-confirmed R-003',
               'runner_real':True,'evidence':str(base)}
    write_json(base/'script_demo.json',summary)
    return base/'script_demo.json'


def prepare(run_root, state_root, controller, proof):
    run_root, state_root, controller = (Path(p).resolve() for p in (run_root,state_root,controller))
    for external in (run_root,state_root):
        if external.is_relative_to(controller) or controller.is_relative_to(external):
            raise PolicyError('M3_ROOT_MUST_BE_EXTERNAL')
    project = run_root/'planning-project'
    project.mkdir(parents=True,exist_ok=False)
    # Preserve the M2 completed candidate and its evidence; work on a new disposable copy.
    previous = read_json(controller/'audit_evidence/m2/execution-01/summary.json')
    old = Path(previous['demo_repository'])
    for name in ('config_loader.py','project_config.py'):
        shutil.copyfile(old/name,project/name)
    subprocess.run(['git','init',str(project)],check=True,capture_output=True)
    store=MapStore(state_root)
    source=read_json(controller/'tests/data/m3/source_requirements.json')
    store.initialize('配置校验扩展：只读规划',source)
    control=MapController(store,controller)
    control.mk('create',basis='MK_CONFIRMED_M3_PLAN',node=seed_node('stage',None,'STAGE',['R-003']))
    control.mk('transition',basis='MK_CONFIRMED_M3_PLAN',node_id='stage',target='READY')
    control.mk('switch_focus',basis='MK_CONFIRMED_M3_PLAN',node_id='stage')
    evidence=store.root/'runs/planning-01'
    raw_output=run_root/'planning-01/raw/proposal.json'
    ai=ReadOnlyAI(project=project,controller=controller,state=store.root,evidence=evidence,proof=proof,raw_output=raw_output)
    request=ai.preview(planning_prompt(source,store.read()['map']))
    prepared={'request':request,'approval_sha256':digest(request),'project_snapshot':snapshot(project),
              'state_sha256':digest(store.read()),'source_sha256':digest(source),'project':str(project),
              'controller':str(controller),'state':str(store.root),'evidence':str(evidence),'proof':str(Path(proof).resolve()),
              'raw_output':str(raw_output),'status':'AWAITING_MK_PROMPT_AND_PARAMETER_APPROVAL','model_calls':0}
    path=evidence/'prepared-request.json';write_json(path,prepared)
    return path


def execute(prepared_path, approved_sha256):
    p=read_json(prepared_path)
    store=MapStore(Path(p['state']))
    if snapshot(Path(p['project'])) != p['project_snapshot'] or digest(store.read()) != p['state_sha256']:
        raise PolicyError('PREPARED_INPUT_CHANGED')
    ai=ReadOnlyAI(project=p['project'],controller=p['controller'],state=p['state'],evidence=p['evidence'],proof=p['proof'],raw_output=p['raw_output'])
    raw=ai.execute_approved(p['request'],approved_sha256)
    controller=MapController(store,p['controller'])
    run_id=p.get('run_id','planning-01')
    try:
        # Validate external raw output before storing any proposal in state.
        proposal=parse_message(raw,'m3_plan_proposal')
        validate_proposal(proposal,store.read()['map'],store.source,fixture_mode=store.fixture_mode)
        result=controller.submit_proposal(raw,proposal_id=run_id,run_id=run_id)
        status='PENDING_MK'
    except Exception as error:
        status='REJECTED: '+str(error);result=store.read()
    report={'status':status,'state':result,'raw_output':p['raw_output'],
            'model_calls':len(read_json(store.root/'runs/planning-call-ledger.json')['calls'])}
    write_json(Path(p['evidence'])/'planning-result.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest='action',required=True)
    demo=sub.add_parser('demo');demo.add_argument('--run-root',type=Path,required=True);demo.add_argument('--controller',type=Path,required=True)
    prep=sub.add_parser('prepare')
    for name in ('run-root','state-root','controller','proof'):prep.add_argument('--'+name,type=Path,required=True)
    ex=sub.add_parser('execute');ex.add_argument('--prepared-request',type=Path,required=True);ex.add_argument('--approved-sha256',required=True)
    mk=sub.add_parser('mk');mk.add_argument('--state-root',type=Path,required=True);mk.add_argument('--controller',type=Path,required=True)
    mk.add_argument('--operation',required=True);mk.add_argument('--basis',required=True);mk.add_argument('--arguments-json',default='{}');mk.add_argument('--expected-revision',type=int,required=True)
    rep=sub.add_parser('report');rep.add_argument('--state-root',type=Path,required=True)
    a=parser.parse_args()
    if a.action=='demo': print(scripted_demo(a.run_root,a.controller))
    elif a.action=='prepare': print(prepare(a.run_root,a.state_root,a.controller,a.proof))
    elif a.action=='execute': print(json.dumps(execute(a.prepared_request,a.approved_sha256),ensure_ascii=False,indent=2))
    elif a.action=='report': print(render(MapStore(a.state_root)))
    else:
        result=MapController(MapStore(a.state_root),a.controller).mk(a.operation,basis=a.basis,
                expected_revision=a.expected_revision,**json.loads(a.arguments_json))
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
