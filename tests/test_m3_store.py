import json
import pytest
from coding_agent.m0 import PolicyError,read_json
from support.m3_samples import setup


def test_rejected_command_appends_without_state_change(tmp_path):
    store,c=setup(tmp_path);before=store.read();files=list((store.root/'history').glob('*.json'))
    old={p:p.read_bytes() for p in files}
    with pytest.raises(PolicyError):c.mk('transition',basis='MK_TEST',node_id='first',target='DONE')
    assert store.read()==before
    assert all(p.read_bytes()==raw for p,raw in old.items())
    last=read_json(sorted((store.root/'history').glob('*.json'))[-1]);assert not last['accepted']


def test_snapshot_is_not_authoritative_and_history_tampering_blocks(tmp_path):
    store,c=setup(tmp_path);before=store.read()
    (store.root/'map.json').write_text('{}',encoding='utf-8')
    assert store.read()==before
    p=sorted((store.root/'history').glob('*.json'))[-1];data=read_json(p)
    data['after']['map']['goal']='forged';p.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(PolicyError,match='HISTORY_INTEGRITY'):store.read()


def test_lock_and_stale_revision_fail_closed(tmp_path):
    store,c=setup(tmp_path)
    with store.locked():
        with pytest.raises(PolicyError,match='STATE_LOCKED'):store.read()
    before=store.read()
    with pytest.raises(PolicyError,match='STALE_MAP'):c.mk('switch_focus',basis='MK_TEST',node_id='stage',expected_revision=0)
    assert store.read()==before
