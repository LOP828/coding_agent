import json
import pytest
from coding_agent.m0 import PolicyError
from coding_agent.map_permissions import protect_draft,binding,AUTO_PROTECTED
from coding_agent.codex_executor import policy_template,sandbox_overrides
from support.m2_samples import task


def test_protections_added_before_approval_and_cannot_overlap(tmp_path):
    card=task()
    with pytest.raises(PolicyError,match='APPROVED'):protect_draft(card)
    card['acceptance_review']['status']='PENDING';card=protect_draft(card)
    b=binding('first',card,tmp_path/'controller',tmp_path/'state',tmp_path/'project')
    assert set(AUTO_PROTECTED)<=set(card['protected_paths'])
    assert str((tmp_path/'state').resolve()).replace('\\','/') in b['protected_resources']
    card['allowed_change_paths']=['src/coding_agent/**']
    with pytest.raises(PolicyError,match='OVERLAPS_PROTECTED'):binding('first',card,tmp_path/'controller',tmp_path/'state',tmp_path/'project')


def test_external_state_denial_is_in_actual_executor_config(tmp_path):
    resources=(tmp_path/'state',)
    assert policy_template(resources)['filesystem']['$PROTECTED_0']=='none'
    args=sandbox_overrides(tmp_path/'project',tmp_path/'controller',tmp_path/'evidence',resources)
    table=next(a for a in args if a.startswith('permissions.m2_provider.filesystem='))
    assert json.dumps((tmp_path/'state').resolve().as_posix())+'="none"' in table


def test_missing_protection_and_internal_state_are_rejected(tmp_path):
    with pytest.raises(PolicyError,match='MISSING'):binding('first',task(),tmp_path/'control',tmp_path/'state',tmp_path/'project')
    with pytest.raises(PolicyError,match='OVERLAPS_PROJECT'):binding('first',task(),tmp_path/'control',tmp_path/'project/state',tmp_path/'project')


def test_nested_external_denials_collapse_to_ancestor(tmp_path):
    state=tmp_path/'state'
    args=sandbox_overrides(tmp_path/'project',tmp_path/'controller',state/'runs/evidence',(state,))
    table=next(a for a in args if a.startswith('permissions.m2_provider.filesystem='))
    assert json.dumps(state.resolve().as_posix())+'="none"' in table
    assert json.dumps((state/'runs/evidence').resolve().as_posix()) not in table
