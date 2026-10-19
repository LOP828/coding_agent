import json,platform
from pathlib import Path
import pytest
from coding_agent.m0 import PolicyError,read_json
from coding_agent.codex_executor import configuration_identity
from coding_agent.readonly_ai import ReadOnlyAI,planning_prompt,policy_template,OUTPUT_SCHEMA
from coding_agent.verification import write_json
from coding_agent.task_map import digest
from coding_agent.workspace import snapshot
from support.m3_samples import ROOT,setup


def ai_setup(tmp_path,monkeypatch,role='PLANNER'):
    monkeypatch.setattr('coding_agent.readonly_ai.runtime_roots',lambda:['/runtime'])
    proof=tmp_path/'proof.json'
    write_json(proof,{'policy_template':policy_template(),'platform':platform.system(),'configuration_identity':configuration_identity(tmp_path/'project'),
                      'usable_for_planning':True,'codex_version':'test-version','fixture_notice':'synthetic, not sandbox evidence'})
    return ReadOnlyAI(project=tmp_path/'project',controller=tmp_path/'controller',state=tmp_path/'state',
                      evidence=tmp_path/'state/runs/planner',proof=proof,raw_output=tmp_path/'raw/proposal.json',role=role)


@pytest.mark.parametrize('role',['PLANNER','REVIEWER'])
def test_all_ai_roles_construct_only_readonly_config(tmp_path,monkeypatch,role):
    ai=ai_setup(tmp_path,monkeypatch,role);r=ai.preview('proposal')
    assert r['policy_template']['filesystem'][':root']=='none'
    assert 'write' not in r['policy_template']['filesystem'].values()
    assert r['model']=='gpt-6-sol' and r['reasoning']=='medium'
    assert '--output-schema' in r['command']
    assert r['command'][r['command'].index('--output-schema')+1]==str(OUTPUT_SCHEMA)
    assert r['command'][r['command'].index('--output-last-message')+1]==str(ai.raw_output)
    assert not ai.raw_output.is_relative_to(ai.state)
    assert not any('bypass' in a or 'danger-full-access' in a or 'workspace-write' in a for a in r['command'])
    with pytest.raises(TypeError):ReadOnlyAI(project='x',controller='y',state='z',evidence='e',proof='p',sandbox='workspace-write')


def test_proof_drift_and_missing_approval_prevent_any_call(tmp_path,monkeypatch):
    ai=ai_setup(tmp_path,monkeypatch);req=ai.preview('proposal')
    with pytest.raises(PolicyError,match='NOT_APPROVED'):ai.execute_approved(req,'bad')
    assert not (tmp_path/'state/runs/planning-call-ledger.json').exists()
    data=read_json(ai.proof);data['usable_for_planning']=False;write_json(ai.proof,data)
    with pytest.raises(PolicyError,match='NOT_VERIFIED'):ai.preview('proposal')


def test_prompt_has_only_generic_clarification_instructions(tmp_path):
    store,c=setup(tmp_path);source=read_json(ROOT/'source_requirements.json')
    prompt=planning_prompt(source,store.read()['map'])
    instructions=prompt.split('冻结需求：',1)[0]
    assert 'questions_for_mk' in instructions and '不要自行假设' in instructions
    assert '被规划项目的代码位于当前工作目录，可只读查看现有文件以确定接口和允许修改的路径。' in instructions
    assert 'provider' not in instructions and 'timeout' not in instructions and 'InvalidConfigError' not in instructions
    assert source['requirements'][0]['raw_text'] in prompt


@pytest.mark.parametrize('destination',['state/raw/proposal.json','controller/raw/proposal.json','project/raw/proposal.json'])
def test_cli_raw_output_cannot_target_protected_directories(tmp_path,destination):
    with pytest.raises(PolicyError,match='RAW_OUTPUT_OVERLAPS_PROTECTED'):
        ReadOnlyAI(project=tmp_path/'project',controller=tmp_path/'controller',state=tmp_path/'state',
                   evidence=tmp_path/'state/runs/planner',proof=tmp_path/'proof.json',raw_output=tmp_path/destination)


def test_cli_output_and_logs_are_external_and_request_cannot_replay(tmp_path,monkeypatch):
    from types import SimpleNamespace
    ai=ai_setup(tmp_path,monkeypatch);ai.project.mkdir()
    monkeypatch.setattr('coding_agent.readonly_ai.subprocess.run',lambda *a,**k:SimpleNamespace(stdout=b'test-version'))
    calls=[]
    def captured(command,**kwargs):
        calls.append(command)
        assert kwargs['evidence']==ai.raw_output.parent/'call-01'
        assert not kwargs['evidence'].is_relative_to(ai.state)
        ai.raw_output.write_bytes(b'{"raw":"synthetic"}')
        return {'exit_code':0,'timed_out':False}
    monkeypatch.setattr('coding_agent.readonly_ai.run_captured',captured)
    request=ai.preview('synthetic test')
    assert ai.execute_approved(request,digest(request))==b'{"raw":"synthetic"}'
    assert not (ai.evidence/'proposal.json').exists()
    with pytest.raises(PolicyError,match='ALREADY_EXECUTED'):
        ai.execute_approved(request,digest(request))
    assert len(calls)==1


def test_authorized_second_call_preserves_first_failure_logs(tmp_path,monkeypatch):
    from types import SimpleNamespace
    ai=ai_setup(tmp_path,monkeypatch);ai.project.mkdir()
    ai.raw_output.parent.mkdir()
    old_log=ai.raw_output.parent/'planner.stdout';old_log.write_bytes(b'first API rejection')
    write_json(ai.state/'runs/planning-call-ledger.json',{
        'counting_unit':'AI_BACKED_CODEX_EXEC_INVOCATION',
        'calls':[{'number':1,'state':'FINISHED','result':{'exit_code':1}}]})
    monkeypatch.setattr('coding_agent.readonly_ai.subprocess.run',lambda *a,**k:SimpleNamespace(stdout=b'test-version'))
    def captured(command,**kwargs):
        assert kwargs['evidence']==ai.raw_output.parent/'call-02'
        ai.raw_output.write_bytes(b'{}')
        return {'exit_code':0,'timed_out':False}
    monkeypatch.setattr('coding_agent.readonly_ai.run_captured',captured)
    req=ai.preview('unchanged prompt')
    assert ai.execute_approved(req,digest(req))==b'{}'
    assert old_log.read_bytes()==b'first API rejection'
    assert len(read_json(ai.state/'runs/planning-call-ledger.json')['calls'])==2


def test_existing_raw_proposal_is_never_overwritten(tmp_path,monkeypatch):
    ai=ai_setup(tmp_path,monkeypatch)
    ai.raw_output.parent.mkdir();ai.raw_output.write_bytes(b'preserve')
    req=ai.preview('proposal')
    with pytest.raises(PolicyError,match='RAW_PROPOSAL_ALREADY_EXISTS'):
        ai.execute_approved(req,digest(req))
    assert ai.raw_output.read_bytes()==b'preserve'
    assert not (ai.state/'runs/planning-call-ledger.json').exists()


@pytest.mark.parametrize('valid',[True,False])
def test_controller_validates_external_proposal_before_storing(tmp_path,monkeypatch,valid):
    from coding_agent.m3_run import execute
    store,_=setup(tmp_path)
    project=tmp_path/'project';project.mkdir()
    proposal=read_json(ROOT/'valid_plan_proposal.json')
    proposal['base_revision']=store.read()['map']['revision'] if valid else 999
    raw=json.dumps(proposal).encode()
    class FakeAI:
        def __init__(self,**kwargs):self.destination=Path(kwargs['raw_output'])
        def execute_approved(self,*args):
            self.destination.parent.mkdir();self.destination.write_bytes(raw)
            write_json(store.root/'runs/planning-call-ledger.json',{'calls':[{'synthetic':True}]})
            return raw
    monkeypatch.setattr('coding_agent.m3_run.ReadOnlyAI',FakeAI)
    before=store.read()['map']
    prepared=tmp_path/'prepared.json'
    write_json(prepared,{'project':str(project),'project_snapshot':snapshot(project),'state':str(store.root),
                        'state_sha256':digest(store.read()),'controller':str(tmp_path/'controller'),
                        'evidence':str(store.root/'runs/planning-01'),'proof':'synthetic',
                        'raw_output':str(tmp_path/'raw/proposal.json'),'request':{}})
    report=execute(prepared,'synthetic')
    assert report['status']==('PENDING_MK' if valid else 'REJECTED: STALE_PROPOSAL')
    assert (store.root/'raw/planning-01/message.bin').exists()==valid
    assert len(store.read()['proposals'])==(1 if valid else 0)
    assert store.read()['map']==before
