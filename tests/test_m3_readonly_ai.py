import json,platform
from pathlib import Path
import pytest
from coding_agent.m0 import PolicyError,read_json
from coding_agent.codex_executor import configuration_identity
from coding_agent.readonly_ai import ReadOnlyAI,planning_prompt,policy_template
from coding_agent.verification import write_json
from support.m3_samples import ROOT,setup


def ai_setup(tmp_path,monkeypatch,role='PLANNER'):
    monkeypatch.setattr('coding_agent.readonly_ai.runtime_roots',lambda:['/runtime'])
    proof=tmp_path/'proof.json'
    write_json(proof,{'policy_template':policy_template(),'platform':platform.system(),'configuration_identity':configuration_identity(tmp_path/'project'),
                      'usable_for_planning':True,'codex_version':'test-version','fixture_notice':'synthetic, not sandbox evidence'})
    return ReadOnlyAI(project=tmp_path/'project',controller=tmp_path/'controller',state=tmp_path/'state',
                      evidence=tmp_path/'state/runs/planner',proof=proof,role=role)


@pytest.mark.parametrize('role',['PLANNER','REVIEWER'])
def test_all_ai_roles_construct_only_readonly_config(tmp_path,monkeypatch,role):
    ai=ai_setup(tmp_path,monkeypatch,role);r=ai.preview('proposal')
    assert r['policy_template']['filesystem'][':root']=='none'
    assert 'write' not in r['policy_template']['filesystem'].values()
    assert r['model']=='gpt-6-sol' and r['reasoning']=='medium'
    assert '--output-schema' in r['command']
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
    assert 'provider' not in instructions and 'timeout' not in instructions and 'InvalidConfigError' not in instructions
    assert source['requirements'][0]['raw_text'] in prompt
