"""API transport may relax constraints; the controller remains authoritative."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from coding_agent.readonly_ai import SCHEMA, OUTPUT_SCHEMA
from support.m3_samples import ROOT, setup
from coding_agent.m0 import read_json


def schemas():
    return read_json(SCHEMA), read_json(OUTPUT_SCHEMA)


def test_api_schema_only_removes_positive_constraints():
    full, api = schemas()
    removed = []
    def relax(schema):
        # This schema uses only positive conjunctions, properties and items;
        # removing constraints below them cannot reject a formerly valid value.
        assert set(schema) <= {'$schema','type','const','enum','properties','items',
                               'required','additionalProperties','pattern','minimum',
                               'minItems','minLength','uniqueItems'}
        result = copy.deepcopy(schema)
        for key in ('uniqueItems', 'minLength'):
            if key in result:
                removed.append(key)
                del result[key]
        if 'properties' in result:
            result['properties'] = {k:relax(v) for k,v in result['properties'].items()}
        if 'items' in result:
            result['items'] = relax(result['items'])
        return result
    assert api == relax(full)
    assert removed.count('uniqueItems') == 5
    assert removed.count('minLength') == 5
    Draft202012Validator.check_schema(full)
    Draft202012Validator.check_schema(api)


@pytest.mark.parametrize('variant',['fixture','empty','questions','unicode','derived','nullable_parent'])
def test_every_full_schema_valid_example_is_also_api_valid(variant):
    value = read_json(ROOT/'valid_plan_proposal.json')
    if variant == 'empty':
        value.update(nodes=[], atomic_task_drafts=[], questions_for_mk=[], base_revision=0)
    elif variant == 'questions':
        value['questions_for_mk'] = [{'question':'请明确此需求。','requirement_refs':['R-003']}]
    elif variant == 'unicode':
        value['nodes'][0]['title'] = '界'
        value['atomic_task_drafts'][0]['properties'][0]['statement'] = '界'
    elif variant == 'derived':
        value['nodes'][0].update(origin='DERIVED',derivation_reason='test derivation')
    elif variant == 'nullable_parent':
        value['nodes'][0]['parent_id'] = None
    full, api = schemas()
    Draft202012Validator(full).validate(value)
    Draft202012Validator(api).validate(value)


@pytest.mark.parametrize('field',[
    ('nodes',0,'requirement_refs'),
    ('atomic_task_drafts',0,'requirement_refs'),
    ('atomic_task_drafts',0,'allowed_change_paths'),
    ('atomic_task_drafts',0,'properties',0,'requirement_refs'),
    ('questions_for_mk',0,'requirement_refs'),
    ('nodes',0,'title'),
    ('atomic_task_drafts',0,'title'),
    ('atomic_task_drafts',0,'allowed_change_paths',0),
    ('atomic_task_drafts',0,'properties',0,'statement'),
    ('questions_for_mk',0,'question'),
])
def test_each_removed_constraint_is_enforced_by_controller(tmp_path,field):
    store, controller = setup(tmp_path)
    before = store.read()
    value = read_json(ROOT/'valid_plan_proposal.json')
    value['base_revision'] = before['map']['revision']
    value['questions_for_mk'] = [{'question':'请明确此需求。','requirement_refs':['R-003']}]
    parent = value
    for key in field[:-1]:
        parent = parent[key]
    target = parent[field[-1]]
    if isinstance(target, list):
        target.append(target[0])
    else:
        parent[field[-1]] = ''
    full, api = schemas()
    Draft202012Validator(api).validate(value)
    with pytest.raises(ValidationError):
        Draft202012Validator(full).validate(value)
    with pytest.raises(ValidationError):
        controller.submit_proposal(json.dumps(value).encode(),proposal_id='invalid',run_id='synthetic')
    assert store.read() == before
