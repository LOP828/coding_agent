import copy,json
import pytest
from coding_agent.m0 import PolicyError,read_json,text_sha256
from coding_agent.task_map import uncovered,digest
from coding_agent.m3_run import seed_node
from coding_agent.map_report import render
from support.m3_samples import setup,ROOT


def test_confirmed_requirement_is_exact():
    source=read_json(ROOT/'source_requirements.json')['requirements'][0]
    assert source['raw_text']=='配置校验需要再加两条规则：provider 只能是 openai 或 local；如果配置里有 timeout，必须是正整数，否则抛出 InvalidConfigError。'
    assert source['sha256_utf8']=='5007ee5cd6c75bf10dd9ff04710fee55d43fce9589ddc56a86a385232d79912e'
    assert (source['source_kind'],source['confirmation'],source['status'])==('USER_MESSAGE','USER_CONFIRMED','FROZEN')


@pytest.mark.parametrize('kind',['UNSOURCED','DERIVED','unknown'])
def test_untraceable_nodes_rejected(tmp_path,kind):
    store,c=setup(tmp_path);n=seed_node('new','stage','ATOMIC',['R-003'])
    if kind=='unknown':n['requirement_refs']=['R-999']
    else:n['origin']=kind
    with pytest.raises(PolicyError):c.mk('create',basis='MK_TEST',node=n)


def test_coverage_is_structural_and_deferral_explicit(tmp_path):
    store,c=setup(tmp_path,fixture=True)
    assert uncovered(store.read()['map'],store.source)==['R-003']
    c.mk('defer_requirement',basis='MK_DEFER_R003',requirement_id='R-003')
    assert uncovered(store.read()['map'],store.source)==[]
    c.mk('restore_requirement',basis='MK_RESTORE',requirement_id='R-003')
    assert 'R-003' in render(store)


def test_questions_reported_and_block_approval_without_map_mutation(tmp_path):
    store,c=setup(tmp_path);before=store.read()['map']
    p=read_json(ROOT/'valid_plan_proposal.json');p['base_revision']=before['revision']
    p['questions_for_mk']=[{'question':'请明确需求约束。','requirement_refs':['R-003']}]
    c.submit_proposal(json.dumps(p).encode(),proposal_id='proposal1',run_id='planner1')
    assert store.read()['map']==before
    assert '待 MK 澄清的问题：\n- 提案 proposal1 / R-003：请明确需求约束。' in render(store)
    with pytest.raises(PolicyError,match='UNRESOLVED_MK_QUESTIONS'):
        c.mk('approve_proposal',basis='MK_APPROVE',proposal_id='proposal1',proposal_sha256=digest(p))


def test_proposal_needs_matching_explicit_approval(tmp_path):
    store,c=setup(tmp_path);p=read_json(ROOT/'valid_plan_proposal.json');p['base_revision']=store.read()['map']['revision']
    c.submit_proposal(json.dumps(p).encode(),proposal_id='proposal1',run_id='planner1')
    assert len(store.read()['map']['nodes'])==3
    with pytest.raises(PolicyError):c.mk('approve_proposal',basis='MK_APPROVE',proposal_id='proposal1',proposal_sha256='wrong')
    c.mk('approve_proposal',basis='MK_APPROVE',proposal_id='proposal1',proposal_sha256=digest(p))
    assert len(store.read()['map']['nodes'])==5
    assert all(n['status']=='PENDING' for n in store.read()['map']['nodes'][-2:])


def test_pending_real_request_is_reported_from_controller_record(tmp_path):
    from coding_agent.verification import write_json
    store,c=setup(tmp_path)
    write_json(store.root/'runs/planning-01/prepared-request.json',{'status':'AWAITING_MK_PROMPT_AND_PARAMETER_APPROVAL'})
    assert '真实规划 planning-01：等待 MK 确认完整提示词与调用参数' in render(store)
