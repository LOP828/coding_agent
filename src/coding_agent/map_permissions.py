"""Controller-owned protections are installed before task approval."""
import copy
from pathlib import Path
from .m0 import PolicyError, path_matches
from .task_map import validate_schema, digest
from .workspace import snapshot

AUTO_PROTECTED = ('src/coding_agent/**', '.coding-agent-state/**', 'map.json', 'findings.json', 'history/**')


def protect_draft(task):
    if task['acceptance_review']['status'] == 'APPROVED':
        raise PolicyError('CANNOT_MUTATE_APPROVED_TASK')
    result = copy.deepcopy(task)
    result['protected_paths'] = sorted(set(result['protected_paths']) | set(AUTO_PROTECTED))
    return result


def binding(node_id, task, controller, state_root, repository):
    controller, state_root, repository = (Path(p).resolve() for p in (controller, state_root, repository))
    for protected in (controller, state_root):
        if protected.is_relative_to(repository) or repository.is_relative_to(protected):
            raise PolicyError('M3_STATE_OR_CONTROLLER_OVERLAPS_PROJECT')
    if not set(AUTO_PROTECTED) <= set(task['protected_paths']):
        raise PolicyError('AUTO_PROTECTION_MISSING_BEFORE_APPROVAL')
    for allowed in task['allowed_change_paths']:
        for protected in task['protected_paths']:
            a, p = allowed.removesuffix('/**'), protected.removesuffix('/**')
            if a == p or path_matches(a, protected) or path_matches(p, allowed):
                raise PolicyError('ALLOWED_PATH_OVERLAPS_PROTECTED')
    value = {'schema_version': 'm3.1', 'node_id': node_id, 'task_sha256': digest(task),
             'protected_paths': task['protected_paths'],
             'protected_resources': [controller.as_posix(), state_root.as_posix()]}
    validate_schema('m3_task_binding', value)
    return value


def protected_snapshot(controller, state_root):
    # Runtime evidence is controller-written during execution; business state is not.
    return {'code': snapshot(Path(controller) / 'src/coding_agent', exclude=('__pycache__',)),
            'state': snapshot(Path(state_root), exclude=('runs', 'exports', '.lock'))}
