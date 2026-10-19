import copy
from pathlib import Path
from coding_agent.m0 import read_json, approval_payload_sha256
from coding_agent.map_store import MapStore
from coding_agent.map_controller import MapController
from coding_agent.map_permissions import protect_draft
from coding_agent.m3_run import seed_node
from coding_agent.runner import Runner
from support.m2_samples import ROOT as M2_ROOT, task

ROOT=Path(__file__).resolve().parents[1]/'data/m3'
CONTROLLER=Path(__file__).resolve().parents[2]


def setup(tmp_path, *, fixture=False):
    source=read_json(ROOT/'source_requirements.json')
    if fixture:
        source['requirements'] += read_json(M2_ROOT/'fixtures/source_requirements.json')['requirements']
    store=MapStore(tmp_path/'state',fixture_mode=fixture)
    store.initialize('test goal',source)
    control=MapController(store,CONTROLLER)
    refs=['R-001'] if fixture else ['R-003']
    for node_id,parent,kind in [('stage',None,'STAGE'),('first','stage','ATOMIC'),('second','stage','ATOMIC')]:
        control.mk('create',basis='MK_TEST',node=seed_node(node_id,parent,kind,refs))
        control.mk('transition',basis='MK_TEST',node_id=node_id,target='READY')
    control.mk('switch_focus',basis='MK_TEST',node_id='stage')
    return store,control


def bound_runner(store,tmp_path):
    card=task();card['acceptance_review']['status']='PENDING';card=protect_draft(card)
    card['acceptance_review']['status']='APPROVED'
    records=read_json(M2_ROOT/'fixtures/trusted_review_records.json')
    sha=approval_payload_sha256(card,store.source)
    card['acceptance_review']['approved_payload_sha256']=sha
    records['review_records'][0]['approved_payload_sha256']=sha
    runner=Runner(M2_ROOT,store.source,records,tmp_path/'runner',fixture_mode=True)
    return card,runner
