"""Pure structural rules. No model, filesystem mutations, or time-based decisions."""
from __future__ import annotations
import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator
from .m0 import PolicyError, text_sha256, validate_path

@lru_cache(maxsize=32)
def _validator(raw):
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)

def validate_schema(name, value):
    raw = (Path(__file__).with_name("schemas") / (name + ".schema.json")).read_text(encoding="utf-8")
    _validator(raw).validate(value)

STATES = ('PENDING', 'READY', 'RUNNING', 'DONE', 'BLOCKED', 'DEFERRED')
TRANSITIONS = {
    'PENDING': {'READY', 'BLOCKED', 'DEFERRED'},
    'READY': {'RUNNING', 'DONE', 'BLOCKED', 'DEFERRED'},
    'RUNNING': {'DONE', 'BLOCKED', 'DEFERRED'},
    'DONE': set(), 'BLOCKED': {'READY', 'DEFERRED'}, 'DEFERRED': {'PENDING'},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate_sources(source, *, fixture_mode=False):
    validate_schema('source_requirements', source)
    records = {r['id']: r for r in source['requirements']}
    if len(records) != len(source['requirements']):
        raise PolicyError('DUPLICATE_REQUIREMENT_ID')
    for r in records.values():
        if text_sha256(r['raw_text']) != r['sha256_utf8']:
            raise PolicyError('SOURCE_HASH_MISMATCH')
        if r['status'] != 'FROZEN':
            raise PolicyError('SOURCE_NOT_FROZEN')
        if r['source_kind'] == 'USER_MESSAGE':
            if r['confirmation'] != 'USER_CONFIRMED':
                raise PolicyError('SOURCE_NOT_CONFIRMED')
        elif not (fixture_mode and r['confirmation'] == 'NOT_APPLICABLE_FIXTURE'):
            raise PolicyError('SYNTHETIC_SOURCE_NOT_ALLOWED')
    return records


def traceable(row, source):
    if row['origin'] == 'UNSOURCED':
        raise PolicyError('UNSOURCED_PROPERTY')
    if row['origin'] == 'DERIVED' and not row['derivation_reason'].strip():
        raise PolicyError('DERIVED_REASON_REQUIRED')
    if not row['requirement_refs'] or not set(row['requirement_refs']) <= {r['id'] for r in source['requirements']}:
        raise PolicyError('UNKNOWN_REQUIREMENT')


def nodes_by_id(task_map):
    return {n['id']: n for n in task_map['nodes']}


def children(task_map, node_id):
    return [n for n in task_map['nodes'] if n['parent_id'] == node_id]


def completable(task_map, node):
    descendants = children(task_map, node['id'])
    return (node['type'] == 'STAGE' and node['status'] == 'READY' and bool(descendants)
            and all(n['status'] == 'DONE' or (n['status'] == 'DEFERRED' and n['deferred_by'])
                    for n in descendants))


def validate_map(task_map, source, *, fixture_mode=False):
    validate_schema('m3_task_map', task_map)
    sources = validate_sources(source, fixture_mode=fixture_mode)
    if task_map['source_sha256'] != digest(source):
        raise PolicyError('SOURCE_REGISTRY_CHANGED')
    nodes = nodes_by_id(task_map)
    if len(nodes) != len(task_map['nodes']):
        raise PolicyError('DUPLICATE_NODE')
    roots = [n for n in nodes.values() if n['parent_id'] is None]
    if nodes and (len(roots) != 1 or roots[0]['type'] != 'STAGE'):
        raise PolicyError('ONE_STAGE_ROOT_REQUIRED')
    for node in nodes.values():
        traceable(node, source)
        parent = node['parent_id']
        if parent is not None and (parent not in nodes or nodes[parent]['type'] != 'STAGE'):
            raise PolicyError('INVALID_PARENT')
        seen = {node['id']}
        while parent is not None:
            if parent in seen:
                raise PolicyError('PARENT_CYCLE')
            seen.add(parent)
            parent = nodes[parent]['parent_id']
        if node['created_by'] == 'AI_APPROVED_BY_MK' and not node['approval_ref']:
            raise PolicyError('AI_NODE_WITHOUT_MK_APPROVAL')
        if node['status'] == 'DEFERRED' and not node['deferred_by']:
            raise PolicyError('DEFERRED_WITHOUT_MK')
        if node['type'] == 'STAGE' and node['status'] == 'RUNNING':
            raise PolicyError('STAGE_CANNOT_RUN')
        if node['type'] == 'STAGE' and node['status'] == 'DONE':
            descendants = children(task_map, node['id'])
            if not descendants or any(c['status'] != 'DONE' and not (c['status'] == 'DEFERRED' and c['deferred_by']) for c in descendants):
                raise PolicyError('COMPLETED_STAGE_CHILDREN_CHANGED')
    running = [n for n in nodes.values() if n['status'] == 'RUNNING']
    if len(running) > 1:
        raise PolicyError('MULTIPLE_RUNNING')
    if task_map['focus'] is not None and task_map['focus'] not in nodes:
        raise PolicyError('INVALID_FOCUS')
    active = task_map['active_run']
    if bool(running) != bool(active) or (running and
            (active['node_id'] != running[0]['id'] or task_map['focus'] != running[0]['id'])):
        raise PolicyError('RUNNING_FOCUS_MISMATCH')
    deferred = task_map['deferred_requirements']
    if len({r['requirement_id'] for r in deferred}) != len(deferred) or any(r['requirement_id'] not in sources for r in deferred):
        raise PolicyError('INVALID_REQUIREMENT_DEFERRAL')


def add_nodes(task_map, additions, source, *, approval=None):
    existing = nodes_by_id(task_map)
    for draft in additions:
        if draft['id'] in existing:
            raise PolicyError('DUPLICATE_NODE')
        parent = existing.get(draft['parent_id'])
        if parent and parent['status'] in ('DONE', 'DEFERRED'):
            raise PolicyError('PARENT_CLOSED')
        row = {**copy.deepcopy(draft), 'status': 'PENDING',
               'created_by': 'AI_APPROVED_BY_MK' if approval else 'MK',
               'approval_ref': approval, 'deferred_by': None}
        traceable(row, source)
        task_map['nodes'].append(row)
        existing[row['id']] = row


def validate_proposal(proposal, task_map, source, *, fixture_mode=False):
    validate_schema('m3_plan_proposal', proposal)
    if proposal['base_revision'] != task_map['revision']:
        raise PolicyError('STALE_PROPOSAL')
    simulated = copy.deepcopy(task_map)
    add_nodes(simulated, proposal['nodes'], source, approval='STRUCTURAL_CHECK_ONLY')
    validate_map(simulated, source, fixture_mode=fixture_mode)
    atomic = {n['id']: n for n in proposal['nodes'] if n['type'] == 'ATOMIC'}
    drafts = proposal['atomic_task_drafts']
    if len({d['node_id'] for d in drafts}) != len(drafts) or {d['node_id'] for d in drafts} != atomic.keys():
        raise PolicyError('DRAFT_NODE_MISMATCH')
    for d in drafts:
        traceable(d, source)
        if set(d['requirement_refs']) != set(atomic[d['node_id']]['requirement_refs']):
            raise PolicyError('DRAFT_SOURCE_MISMATCH')
        covered = set()
        for p in d['properties']:
            traceable(p, source)
            if not set(p['requirement_refs']) <= set(d['requirement_refs']):
                raise PolicyError('PROPERTY_SOURCE_OUTSIDE_TASK')
            covered.update(p['requirement_refs'])
        if covered != set(d['requirement_refs']):
            raise PolicyError('UNCOVERED_TASK_REQUIREMENT')
        for path in d['allowed_change_paths']:
            validate_path(path, pattern=True)
    for q in proposal['questions_for_mk']:
        if not set(q['requirement_refs']) <= {r['id'] for r in source['requirements']}:
            raise PolicyError('UNKNOWN_QUESTION_REQUIREMENT')


def uncovered(task_map, source):
    covered = {r for n in task_map['nodes'] for r in n['requirement_refs']}
    deferred = {r['requirement_id'] for r in task_map['deferred_requirements']}
    return sorted({r['id'] for r in source['requirements']} - covered - deferred)
