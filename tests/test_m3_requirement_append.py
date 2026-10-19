import copy
from pathlib import Path

import pytest

from coding_agent.m0 import PolicyError, read_json, text_sha256
from coding_agent.map_store import MapStore
from coding_agent.task_map import digest, validate_proposal
from support.m3_samples import setup, ROOT

RECORD = Path(__file__).resolve().parents[1]/'docs/M3/R004_Frozen_Requirement.json'


def test_r004_is_exact_mk_confirmed_text():
    row = read_json(RECORD)
    assert row['raw_text'] == 'R-004（对 R-003 的澄清）：provider 存在但不是 openai 或 local 时，同样抛出 InvalidConfigError；缺少 provider 时仍按原规则抛出 MissingProviderError。timeout 必须是整数类型且大于 0；布尔值、字符串（例如 "30"）、浮点数（例如 30.0）一律视为不合法，抛出 InvalidConfigError。'
    assert row['sha256_utf8'] == text_sha256(row['raw_text']) == '96d41bbd9a9586198e49ecb757de345469fa8910af75043c7e1c957293b507d8'
    assert (row['source_kind'],row['confirmation'],row['status']) == ('USER_MESSAGE','USER_CONFIRMED','FROZEN')


def test_append_keeps_historical_sources_events_and_proposals(tmp_path):
    store,c = setup(tmp_path)
    before = store.read(); source = store.source
    original_path = store.root/'requirements/source_requirements.json'
    original_bytes = original_path.read_bytes()
    events = {p:p.read_bytes() for p in (store.root/'history').glob('*.json')}
    proposal = read_json(ROOT/'valid_plan_proposal.json')
    proposal['base_revision'] = before['map']['revision']
    row = read_json(RECORD)
    c.mk('append_requirement',basis='MK_CONFIRMED_R004',expected_revision=before['map']['revision'],requirement=row)
    after = MapStore(store.root).read()
    assert store.source['requirements'] == source['requirements']+[row]
    assert original_path.read_bytes() == original_bytes
    assert all(p.read_bytes()==raw for p,raw in events.items())
    expected = copy.deepcopy(before)
    expected['map']['revision'] += 1
    expected['map']['source_sha256'] = digest(store.source)
    assert after == expected
    assert store._source_for(before['map']['source_sha256']) == source
    with pytest.raises(PolicyError,match='STALE_PROPOSAL'):
        validate_proposal(proposal,after['map'],store.source)


@pytest.mark.parametrize('bad',['duplicate','hash','unconfirmed','stale'])
def test_invalid_requirement_append_leaves_state_and_source_unchanged(tmp_path,bad):
    store,c = setup(tmp_path); before = store.read(); source = store.source
    row = read_json(RECORD); revision = before['map']['revision']
    if bad == 'duplicate': row['id'] = 'R-003'
    elif bad == 'hash': row['raw_text'] += 'tampered'
    elif bad == 'unconfirmed': row['confirmation'] = 'PENDING'
    else: revision -= 1
    with pytest.raises(PolicyError):
        c.mk('append_requirement',basis='MK_TEST',expected_revision=revision,requirement=row)
    assert store.read() == before
    assert store.source == source


def test_version_tampering_blocks_replay(tmp_path):
    store,c = setup(tmp_path)
    c.mk('append_requirement',basis='MK_CONFIRMED_R004',requirement=read_json(RECORD))
    sha = store.read()['map']['source_sha256']
    (store.root/'requirements/versions'/f'{sha}.json').write_text('{}',encoding='utf-8')
    with pytest.raises(PolicyError,match='SOURCE_REGISTRY_CHANGED'):
        store.read()
