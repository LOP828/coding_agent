"""Strict submission parsing and archival; never infer intent from free text."""
import hashlib
import re
from .isolated_verification import strict_json
from .m0 import PolicyError
from .task_map import validate_schema, nodes_by_id


def parse_message(raw, schema):
    try:
        value = strict_json(raw)
    except (ValueError, UnicodeError):
        text = raw.decode('utf-8')
        blocks = re.findall(r'```json\s*\n(.*?)\n```', text, flags=re.DOTALL)
        if len(blocks) != 1:
            raise PolicyError('EXPECTED_ONE_JSON_MESSAGE')
        value = strict_json(blocks[0].encode('utf-8'))
    validate_schema(schema, value)
    return value


def archive_raw(store, raw, submission_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', submission_id):
        raise PolicyError('INVALID_SUBMISSION_ID')
    folder = store.root / 'raw' / submission_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'message.bin').write_bytes(raw)
    return folder


def ingest(store, raw, *, node_id, run_id, submission_id, submitted_by='EXECUTOR'):
    if submitted_by not in ('EXECUTOR', 'PLANNER', 'MK'):
        raise PolicyError('INVALID_SUBMISSION_SOURCE')
    folder = archive_raw(store, raw, submission_id)
    def reduce(state):
        message = parse_message(raw, 'm3_finding_message')
        if message['source_node_id'] != node_id or node_id not in nodes_by_id(state['map']):
            raise PolicyError('FINDING_SOURCE_MISMATCH')
        for index, finding in enumerate(message['findings']):
            state['findings'].append(dict(schema_version='m3.1', finding_id=f'{submission_id}-{index}',
                source_node_id=node_id, source_run_id=run_id, content=finding['content'],
                submitted_by=submitted_by, evidence_refs=finding['evidence_refs'],
                raw_submission_sha256=hashlib.sha256(raw).hexdigest(), status='OPEN',
                decision_ref=None, promoted_node_id=None))
    try:
        return store.transact(submitted_by, 'submit_findings', f'{run_id}:{submission_id}', reduce)
    except Exception as error:
        (folder / 'parse-error.txt').write_text(str(error), encoding='utf-8')
        raise
