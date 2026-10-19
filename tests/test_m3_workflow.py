import json
from pathlib import Path
import pytest
from coding_agent.m0 import PolicyError,read_json
from coding_agent.task_map import nodes_by_id
from coding_agent.map_report import render
from support.m3_samples import setup,bound_runner,ROOT
from support.m1_samples import repository
from support.m2_samples import source_executor

GOOD="class MissingProviderError(ValueError): pass\ndef validate_config(config):\n    if 'provider' not in config: raise MissingProviderError('missing')\n    return config\n"
BAD="class MissingProviderError(ValueError): pass\ndef validate_config(config): return {'provider':'local',**config}\n"


@pytest.mark.parametrize('sequence,final,retries',[(('good',),'DONE',1),(('bad','good'),'DONE',2),(('bad','bad'),'BLOCKED',2),(('crash',),'BLOCKED',1)])
def test_real_runner_final_result_and_retry_lifecycle(tmp_path,sequence,final,retries):
    store,c=setup(tmp_path,fixture=True);card,runner=bound_runner(store,tmp_path)
    states=[]
    def factory(number,prompt):
        states.append(store.read()['map'])
        kind=sequence[number-1]
        executor=source_executor(GOOD if kind=='good' else BAD if kind=='bad' else "raise ImportError('broken')")
        executor.findings_message=(ROOT/'valid_finding_message.json').read_bytes() if number==1 else None
        return executor
    result=c.execute('first',card,runner,lambda n:repository(tmp_path/f'repo{n}'),factory,basis='MK_START')
    state=store.read();assert nodes_by_id(state['map'])['first']['status']==final
    assert len(result['attempts'])==retries
    assert all(nodes_by_id(m)['first']['status']=='RUNNING' for m in states)
    history=[read_json(p) for p in sorted((store.root/'history').glob('*.json'))]
    finals=[e for e in history if e['operation']=='runner_final'];assert len(finals)==1
    assert len({m['active_run']['run_id'] for m in states})==1
    assert state['map']['focus']==('stage' if final=='DONE' else 'first')
    assert state['findings'][0]['status']=='OPEN'
    assert 'R-003' in render(store)
    if final=='DONE':
        assert all(r['status']=='PASS' for r in result['attempts'][-1]['report']['results'])


def test_fake_runner_pass_cannot_complete_node(tmp_path):
    store,c=setup(tmp_path,fixture=True);card,_=bound_runner(store,tmp_path)
    class Fake:
        def run(self,*args):return {'report':{'gate':{'status':'PASS'}}}
    with pytest.raises(PolicyError,match='REAL_RUNNER'):
        c.execute('first',card,Fake(),lambda n:None,lambda n,p:None,basis='MK_START')
    assert nodes_by_id(store.read()['map'])['first']['status']=='READY'


def test_executor_outside_allowlist_hard_fails_then_stops(tmp_path):
    store,c=setup(tmp_path,fixture=True);card,runner=bound_runner(store,tmp_path)
    def factory(number,prompt):
        def executor(repo):
            source_executor(GOOD)(repo)
            (repo/'project_config.py').write_text('tampered',encoding='utf-8')
        return executor
    result=c.execute('first',card,runner,lambda n:repository(tmp_path/f'repo{n}'),factory,basis='MK_START')
    assert len(result['attempts'])==2
    assert result['attempts'][-1]['report']['gate']['status']=='HARD_FAIL'
    assert nodes_by_id(store.read()['map'])['first']['status']=='BLOCKED'


def test_mk_stop_keeps_running_until_executor_returns(tmp_path):
    store,c=setup(tmp_path,fixture=True);card,runner=bound_runner(store,tmp_path)
    def factory(number,prompt):
        def executor(repo):
            c.mk('transition',basis='MK_STOP_AND_DEFER',node_id='first',target='DEFERRED')
            assert nodes_by_id(store.read()['map'])['first']['status']=='RUNNING'
            assert store.read()['map']['active_run'] is not None
            source_executor(GOOD)(repo)
        return executor
    result=c.execute('first',card,runner,lambda n:repository(tmp_path/f'repo{n}'),factory,basis='MK_START')
    assert len(result['attempts'])==1
    assert nodes_by_id(store.read()['map'])['first']['status']=='DEFERRED'
    assert store.read()['map']['active_run'] is None
