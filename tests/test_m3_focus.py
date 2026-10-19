import pytest
from coding_agent.m0 import PolicyError
from coding_agent.m3_run import seed_node
from support.m3_samples import setup,bound_runner
from support.m1_samples import repository


def test_other_branch_requires_explicit_focus_command(tmp_path):
    store,c=setup(tmp_path,fixture=True)
    c.mk('create',basis='MK_TEST',node=seed_node('other','stage','STAGE',['R-001']))
    c.mk('transition',basis='MK_TEST',node_id='other',target='READY')
    c.mk('switch_focus',basis='MK_SWITCH',node_id='other')
    card,runner=bound_runner(store,tmp_path)
    with pytest.raises(PolicyError,match='PARENT_FOCUS'):
        c.execute('first',card,runner,lambda n:pytest.fail('must not create candidate'),lambda n,p:None,basis='MK_START')
    assert store.read()['map']['focus']=='other'


def test_generic_transition_never_starts_sibling(tmp_path):
    store,c=setup(tmp_path)
    with pytest.raises(PolicyError,match='BOUND_RUN'):
        c.mk('transition',basis='UNAUTHORIZED_EXECUTION_REQUEST',node_id='second',target='RUNNING')
    assert store.read()['map']['focus']=='stage'
