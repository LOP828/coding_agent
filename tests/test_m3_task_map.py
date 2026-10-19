import copy
import pytest
from coding_agent.m0 import PolicyError
from coding_agent.task_map import validate_map,TRANSITIONS
from coding_agent.m3_run import seed_node
from support.m3_samples import setup


def test_matrix_is_explicit_and_terminal():
    assert TRANSITIONS=={'PENDING':{'READY','BLOCKED','DEFERRED'},'READY':{'RUNNING','DONE','BLOCKED','DEFERRED'},
        'RUNNING':{'DONE','BLOCKED','DEFERRED'},'DONE':set(),'BLOCKED':{'READY','DEFERRED'},'DEFERRED':{'PENDING'}}


@pytest.mark.parametrize('target',['PENDING','RUNNING','DONE'])
def test_atomic_ready_cannot_bypass_runner(tmp_path,target):
    store,c=setup(tmp_path);before=store.read()
    with pytest.raises(PolicyError):c.mk('transition',basis='MK_TEST',node_id='first',target=target)
    assert store.read()==before


def test_stage_done_requires_mk_and_all_children(tmp_path):
    store,c=setup(tmp_path)
    with pytest.raises(PolicyError):c.mk('transition',basis='MK_TEST',node_id='stage',target='DONE')
    for name in ('first','second'):c.mk('transition',basis='MK_DEFER',node_id=name,target='DEFERRED')
    assert store.read()['map']['nodes'][0]['status']=='READY'
    c.mk('transition',basis='MK_COMPLETE',node_id='stage',target='DONE')
    with pytest.raises(PolicyError,match='COMPLETED_STAGE_CHILDREN_CHANGED'):
        c.mk('transition',basis='MK_UNDEFER',node_id='first',target='PENDING')
    with pytest.raises(PolicyError):c.mk('transition',basis='MK_TEST',node_id='stage',target='READY')


def test_recovery_and_deferral_require_explicit_commands(tmp_path):
    store,c=setup(tmp_path)
    for target in ('BLOCKED','READY','DEFERRED','PENDING','READY'):
        c.mk('transition',basis='MK_TEST',node_id='first',target=target)
    assert store.read()['map']['nodes'][1]['status']=='READY'


@pytest.mark.parametrize('kind',['duplicate','atomic_parent','cycle','two_running'])
def test_graph_and_single_running_invariants(tmp_path,kind):
    store,c=setup(tmp_path);m=store.read()['map']
    if kind=='duplicate':m['nodes'].append(copy.deepcopy(m['nodes'][1]))
    if kind=='atomic_parent':m['nodes'][2]['parent_id']='first'
    if kind=='cycle':m['nodes'][0]['parent_id']='stage'
    if kind=='two_running':
        m['nodes'][1]['status']=m['nodes'][2]['status']='RUNNING'
    with pytest.raises(PolicyError):validate_map(m,store.source)
