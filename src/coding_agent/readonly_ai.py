"""Read-only AI proposal adapter. All role entrypoints construct the same read-only policy."""
from pathlib import Path
import hashlib
import json
import platform
import subprocess
import shutil
from .codex_executor import CallLedger, configuration_identity
from .m0 import PolicyError, read_json
from .python_environment import clean_environment
from .task_map import digest
from .verification import run_captured, write_json
from .workspace import snapshot

PROFILE = 'm3_readonly'
SCHEMA = Path(__file__).with_name('schemas') / 'm3_plan_proposal.schema.json'


def runtime_roots():
    if platform.system() != 'Linux':
        raise PolicyError('READONLY_SANDBOX_PLATFORM_NOT_VERIFIED')
    cli = shutil.which('codex')
    if not cli:
        raise PolicyError('CODEX_NOT_INSTALLED')
    package = Path(cli).resolve().parents[1]
    return [package.as_posix()]


def policy_template():
    return {'profile': PROFILE, 'filesystem': {':root': 'none', ':minimal': 'read',
            **{p: 'read' for p in runtime_roots()}, '$PROJECT': 'read',
            '$CONTROLLER': 'none', '$STATE': 'none'}, 'network': False,
            'features': {'multi_agent': False, 'apps': False}}


def readonly_overrides(project, controller, state):
    paths = {'$PROJECT': str(Path(project).resolve()), '$CONTROLLER': str(Path(controller).resolve()),
             '$STATE': str(Path(state).resolve())}
    fs = {paths.get(k, k): v for k, v in policy_template()['filesystem'].items()}
    table = '{' + ','.join(json.dumps(k) + '=' + json.dumps(v) for k, v in fs.items()) + '}'
    values = [f'default_permissions="{PROFILE}"', f'permissions.{PROFILE}.filesystem={table}',
              f'permissions.{PROFILE}.network.enabled=false', 'approval_policy="never"',
              'features.multi_agent=false', 'features.apps=false']
    return [item for value in values for item in ('-c', value)]


def planning_prompt(source, task_map):
    # Instructions are generic. The requirement itself is transmitted verbatim as frozen data.
    return ('你是只读规划器。根据冻结需求和当前任务地图，提出 2–3 个原子任务及任务卡草稿。\n'
            '只输出符合给定 JSON Schema 的提案；不写文件，不执行任务，不批准提案，不宣告完成。\n'
            '需求不明确时，在 questions_for_mk 列出待 MK 澄清的问题；不要自行假设并写入任务卡草稿。\n'
            '节点与草稿引用冻结需求 ID。只做提案，等待 MK 决策。\n'
            '冻结需求：\n' + json.dumps(source, ensure_ascii=False, indent=2) +
            '\n当前地图：\n' + json.dumps(task_map, ensure_ascii=False, indent=2) + '\n')


class ReadOnlyAI:
    def __init__(self, *, project, controller, state, evidence, proof, role='PLANNER',
                 model='gpt-6-sol', reasoning='medium', timeout=300):
        if role not in ('PLANNER', 'REVIEWER') or model not in ('gpt-6-sol', 'gpt-6-luna') or reasoning != 'medium' or timeout <= 0:
            raise PolicyError('INVALID_READONLY_AI_CONFIGURATION')
        self.project, self.controller, self.state, self.evidence, self.proof = (
            Path(p).resolve() for p in (project, controller, state, evidence, proof))
        for protected in (self.controller, self.state, self.evidence):
            if protected.is_relative_to(self.project) or self.project.is_relative_to(protected):
                raise PolicyError('READONLY_PROJECT_OVERLAPS_PROTECTED')
        self.role, self.model, self.reasoning, self.timeout = role, model, reasoning, timeout

    def preview(self, prompt):
        proof = read_json(self.proof)
        identity = configuration_identity(self.project)
        if (proof.get('policy_template') != policy_template() or proof.get('platform') != platform.system()
                or proof.get('configuration_identity') != identity or not proof.get('usable_for_planning')):
            raise PolicyError('READONLY_SANDBOX_NOT_VERIFIED')
        args = ['codex', '--no-daemon', 'exec', '--ephemeral', '-C', str(self.project),
                '-m', self.model, '-c', f'model_reasoning_effort="{self.reasoning}"',
                *readonly_overrides(self.project, self.controller, self.state),
                '--output-schema', str(SCHEMA), '--output-last-message', str(self.evidence / 'proposal.json'),
                '--json', '--color', 'never', '-']
        return {'command': args, 'cwd': str(self.project), 'prompt': prompt, 'role': self.role,
                'model': self.model, 'reasoning': self.reasoning, 'timeout_seconds': self.timeout,
                'configuration_identity': identity, 'policy_template': policy_template(),
                'proof_sha256': hashlib.sha256(self.proof.read_bytes()).hexdigest(),
                'schema_sha256': hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
                'tested_codex_version': proof['codex_version']}

    def execute_approved(self, request, approved_sha256):
        if digest(request) != approved_sha256 or self.preview(request['prompt']) != request:
            raise PolicyError('READONLY_REQUEST_NOT_APPROVED_OR_CHANGED')
        if (self.evidence / 'execution.json').exists():
            raise PolicyError('REQUEST_ALREADY_EXECUTED')
        version = subprocess.run(['codex', '--version'], capture_output=True, check=True, timeout=30).stdout.decode('utf-8').strip()
        if version != request['tested_codex_version']:
            raise PolicyError('CODEX_VERSION_DIFFERS_FROM_PROBE')
        ledger = CallLedger(self.state / 'runs/planning-call-ledger.json', limit=5)
        before = snapshot(self.project)
        write_json(self.evidence / 'request.json', request)
        number = ledger.reserve(request)
        try:
            result = run_captured(request['command'], cwd=self.project, env=clean_environment(),
                                  evidence=self.evidence, prefix='planner', timeout=self.timeout,
                                  stdin=request['prompt'].encode('utf-8'))
        except Exception as error:
            failed = {'launch_error': type(error).__name__, 'call_number': number}
            ledger.finish(number, failed)
            write_json(self.evidence / 'execution.json', failed)
            raise
        after = snapshot(self.project)
        result.update(call_number=number, before=before, after=after, version=version)
        ledger.finish(number, result)
        write_json(self.evidence / 'execution.json', result)
        if before != after or result['timed_out'] or result['exit_code'] != 0:
            raise PolicyError('READONLY_AI_EXECUTION_FAILED')
        return (self.evidence / 'proposal.json').read_bytes()
