"""Single-writer, append-only event authority; snapshots are rebuildable projections."""
from __future__ import annotations
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
from .m0 import PolicyError, read_json
from .task_map import validate_schema, digest, validate_map, validate_sources


class MapStore:
    def __init__(self, root: Path, *, fixture_mode=False):
        self.root = root.resolve()
        self.fixture_mode = fixture_mode

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / '.lock'
        try:
            lock.mkdir()
        except FileExistsError as error:
            raise PolicyError('STATE_LOCKED') from error
        try:
            yield
        finally:
            lock.rmdir()

    @property
    def source(self):
        state = self._read()[0]
        return self._source_for(state['map']['source_sha256'])

    def _source_for(self, sha):
        if not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise PolicyError('INVALID_SOURCE_REGISTRY_HASH')
        original = read_json(self.root / 'requirements/source_requirements.json')
        if digest(original) == sha:
            return original
        path = self.root / 'requirements/versions' / (sha + '.json')
        if not path.is_file():
            raise PolicyError('SOURCE_REGISTRY_VERSION_MISSING')
        source = read_json(path)
        if digest(source) != sha:
            raise PolicyError('SOURCE_REGISTRY_CHANGED')
        return source

    def _validate(self, state):
        validate_map(state['map'], self._source_for(state['map']['source_sha256']), fixture_mode=self.fixture_mode)
        validate_schema('m3_findings', state['findings'])

    def _read(self):
        history = self.root / 'history'
        state, previous = None, None
        paths = sorted(history.glob('*.json'))
        if not paths:
            raise PolicyError('STATE_NOT_INITIALIZED')
        for sequence, path in enumerate(paths, 1):
            event = read_json(path)
            validate_schema('m3_event', event)
            unsigned = {k: v for k, v in event.items() if k != 'sha256'}
            if (path.name != f'{sequence:08d}.json' or event['sequence'] != sequence or
                    event['previous_sha256'] != previous or event['before'] != state or
                    digest(unsigned) != event['sha256']):
                raise PolicyError('HISTORY_INTEGRITY_FAILURE')
            if not event['accepted'] and event['before'] != event['after']:
                raise PolicyError('REJECTED_EVENT_MUTATED_STATE')
            if state and state['map']['source_sha256'] != event['after']['map']['source_sha256']:
                old = self._source_for(state['map']['source_sha256'])
                new = self._source_for(event['after']['map']['source_sha256'])
                if (event['actor'] != 'MK' or event['operation'] != 'append_requirement'
                        or not event['accepted'] or new['schema_version'] != old['schema_version']
                        or len(new['requirements']) != len(old['requirements']) + 1
                        or new['requirements'][:-1] != old['requirements']):
                    raise PolicyError('SOURCE_REGISTRY_NOT_APPEND_ONLY')
            state, previous = event['after'], event['sha256']
            self._validate(state)
        return state, len(paths), previous

    def read(self):
        with self.locked():
            return copy.deepcopy(self._read()[0])

    def _project(self, state):
        for name, data in [('map.json', state['map']), ('findings.json', state['findings'])]:
            temp = self.root / (name + '.pending')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            os.replace(temp, self.root / name)

    def _append(self, before, after, sequence, previous, actor, operation, basis, accepted, reason=''):
        event = dict(sequence=sequence, actor=actor, timestamp=datetime.now(timezone.utc).isoformat(),
                     operation=operation, basis=basis, accepted=accepted, reason=reason,
                     before=before, after=after, previous_sha256=previous)
        event['sha256'] = digest(event)
        validate_schema('m3_event', event)
        path = self.root / 'history' / f'{sequence:08d}.json'
        with path.open('x', encoding='utf-8', newline='\n') as f:
            json.dump(event, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        self._project(after)

    def initialize(self, goal, source):
        with self.locked():
            if (self.root / 'history').exists():
                raise PolicyError('STATE_ALREADY_INITIALIZED')
            (self.root / 'requirements').mkdir(exist_ok=True)
            path = self.root / 'requirements/source_requirements.json'
            with path.open('x', encoding='utf-8') as f:
                json.dump(source, f, ensure_ascii=False, indent=2)
            state = {'map': {'schema_version': 'm3.1', 'revision': 0, 'goal': goal,
                            'source_sha256': digest(source), 'focus': None, 'active_run': None,
                            'nodes': [], 'deferred_requirements': []}, 'findings': [], 'proposals': []}
            self._validate(state)
            (self.root / 'history').mkdir()
            self._append(None, state, 1, None, 'MK', 'initialize', 'MK initialized project', True)

    def transact(self, actor, operation, basis, reducer, *, expected_revision=None):
        if not basis or actor not in ('MK', 'CONTROL', 'EXECUTOR', 'PLANNER'):
            raise PolicyError('INVALID_EVENT_AUTHORITY')
        failure = None
        with self.locked():
            before, sequence, previous = self._read()
            after = copy.deepcopy(before)
            try:
                if expected_revision is not None and before['map']['revision'] != expected_revision:
                    raise PolicyError('STALE_MAP_REVISION')
                reducer(after)
                self._validate(after)
                # Findings/proposals do not change the map revision or invalidate proposals.
                if after['map'] != before['map']:
                    after['map']['revision'] = before['map']['revision'] + 1
            except Exception as error:
                failure = error
                after = before
            self._append(before, after, sequence + 1, previous, actor, operation, basis,
                         failure is None, '' if failure is None else str(failure))
        if failure:
            raise failure
        return after

    def append_requirement(self, requirement, *, basis, expected_revision=None):
        def reduce(state):
            if state['map']['active_run']:
                raise PolicyError('RUN_ACTIVE')
            if (requirement.get('source_kind'), requirement.get('confirmation'), requirement.get('status')) != (
                    'USER_MESSAGE', 'USER_CONFIRMED', 'FROZEN'):
                raise PolicyError('APPEND_REQUIRES_MK_CONFIRMED_FROZEN_REQUIREMENT')
            source = copy.deepcopy(self._source_for(state['map']['source_sha256']))
            source['requirements'].append(copy.deepcopy(requirement))
            validate_sources(source, fixture_mode=self.fixture_mode)
            sha = digest(source)
            folder = self.root / 'requirements/versions'
            folder.mkdir(exist_ok=True)
            path = folder / (sha + '.json')
            if path.exists():
                if read_json(path) != source:
                    raise PolicyError('SOURCE_REGISTRY_CHANGED')
            else:
                with path.open('x', encoding='utf-8', newline='\n') as f:
                    json.dump(source, f, ensure_ascii=False, indent=2)
                    f.write('\n'); f.flush(); os.fsync(f.fileno())
            state['map']['source_sha256'] = sha
        return self.transact('MK', 'append_requirement', basis, reduce, expected_revision=expected_revision)
