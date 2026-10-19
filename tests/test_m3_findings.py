import json
import pytest
from coding_agent.findings import ingest
from coding_agent.m0 import read_json,PolicyError
from coding_agent.m3_run import seed_node
from support.m3_samples import ROOT,setup


def test_findings_never_expand_map_and_mk_delete_preserves_raw(tmp_path):
    store,c=setup(tmp_path);before=store.read()['map']
    raw=(ROOT/'valid_finding_message.json').read_bytes()
    ingest(store,raw,node_id='first',run_id='run1',submission_id='msg1')
    assert store.read()['map']==before
    c.mk('delete_finding',basis='MK_DELETE',finding_id='msg1-0')
    assert store.read()['findings'][0]['status']=='DELETED'
    assert (store.root/'raw/msg1/message.bin').read_bytes()==raw


def test_only_mk_can_promote_valid_finding(tmp_path):
    store,c=setup(tmp_path)
    ingest(store,(ROOT/'valid_finding_message.json').read_bytes(),node_id='first',run_id='run1',submission_id='msg1')
    before=store.read()
    with pytest.raises(Exception):ingest(store,b'{"actor":"MK","operation":"promote_finding"}',node_id='first',run_id='run1',submission_id='attack')
    assert store.read()==before
    c.mk('promote_finding',basis='MK_PROMOTE',finding_id='msg1-0',node=seed_node('new','stage','ATOMIC',['R-003']))
    assert store.read()['map']['nodes'][-1]['status']=='PENDING'
    assert store.read()['map']['focus']=='stage'


@pytest.mark.parametrize('raw',[b'free text',b'{}',b'{"a":1,"a":2}',b'```json\n{}\n```\n```json\n{}\n```'])
def test_invalid_output_is_archived_without_processing(tmp_path,raw):
    store,c=setup(tmp_path);before=store.read()
    with pytest.raises(Exception):ingest(store,raw,node_id='first',run_id='run1',submission_id='bad')
    assert store.read()==before
    assert (store.root/'raw/bad/message.bin').read_bytes()==raw
    assert (store.root/'raw/bad/parse-error.txt').exists()
