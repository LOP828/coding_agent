"""Explicit MK operations and one atomic RUNNING lifecycle around the M2 retry loop.

The local MK entrypoint is trusted operator input, not authentication of arbitrary
same-user programs. AI data never dispatches MK commands.
"""
from __future__ import annotations
import copy
from pathlib import Path
from .findings import archive_raw, ingest, parse_message
from .m0 import PolicyError, validate_admission
from .m2_run import run_attempts
from .map_permissions import binding, protected_snapshot
from .runner import Runner
from .task_map import (TRANSITIONS, add_nodes, children, completable, digest,
                       nodes_by_id, validate_proposal)
from .verification import write_json


class MapController:
    def __init__(self, store, controller_root):
        self.store = store
        self.controller_root = Path(controller_root).resolve()

    def mk(self, operation, *, basis, expected_revision=None, **args):
        def reduce(state):
            m = state['map']; nodes = nodes_by_id(m)
            node = nodes.get(args.get('node_id'))
            if operation == 'create':
                if m['active_run']:
                    raise PolicyError('RUN_ACTIVE')
                add_nodes(m, [args['node']], self.store.source)
            elif operation == 'switch_focus':
                if m['active_run']:
                    raise PolicyError('STOP_RUNNING_BEFORE_SWITCH')
                if not node or node['type'] != 'STAGE' or node['status'] != 'READY':
                    raise PolicyError('FOCUS_REQUIRES_READY_STAGE')
                m['focus'] = node['id']
            elif operation == 'transition':
                if not node:
                    raise PolicyError('UNKNOWN_NODE')
                target = args['target']
                if target not in TRANSITIONS[node['status']]:
                    raise PolicyError('ILLEGAL_TRANSITION')
                if target == 'RUNNING':
                    raise PolicyError('USE_BOUND_RUN_ENTRYPOINT')
                if node['status'] == 'RUNNING':
                    if target not in ('BLOCKED', 'DEFERRED'):
                        raise PolicyError('RUN_PROCESS_NOT_CONFIRMED_STOPPED')
                    m['active_run']['stop_target'] = target
                    if target == 'DEFERRED':
                        node['deferred_by'] = basis
                    return  # Graceful stop: keep RUNNING until the current process exits.
                if target == 'DONE' and not completable(m, node):
                    raise PolicyError('DONE_REQUIRES_STAGE_WITH_COMPLETED_CHILDREN')
                if target == 'DEFERRED' and node['type'] == 'STAGE':
                    if any(c['status'] != 'DONE' and not (c['status'] == 'DEFERRED' and c['deferred_by']) for c in children(m, node['id'])):
                        raise PolicyError('UNFINISHED_CHILDREN')
                if target == 'DEFERRED':
                    node['deferred_by'] = basis
                    if m['focus'] == node['id']:
                        m['focus'] = node['parent_id']
                if node['status'] == 'DEFERRED':
                    node['deferred_by'] = None
                node['status'] = target
                if target == 'DONE' and m['focus'] == node['id']:
                    m['focus'] = node['parent_id']
            elif operation in ('approve_proposal', 'reject_proposal'):
                if m['active_run']:
                    raise PolicyError('RUN_ACTIVE')
                record = next((p for p in state['proposals'] if p['id'] == args['proposal_id']), None)
                if not record or record['status'] != 'PENDING_MK':
                    raise PolicyError('PROPOSAL_NOT_PENDING')
                if record['sha256'] != args['proposal_sha256']:
                    raise PolicyError('PROPOSAL_APPROVAL_HASH_MISMATCH')
                if operation == 'reject_proposal':
                    record.update(status='REJECTED', decision_ref=basis)
                    return  # Preserve the proposal and raw archive; never add its nodes.
                proposal = record['proposal']
                validate_proposal(proposal, m, self.store.source, fixture_mode=self.store.fixture_mode)
                if proposal['questions_for_mk']:
                    raise PolicyError('UNRESOLVED_MK_QUESTIONS')
                add_nodes(m, proposal['nodes'], self.store.source, approval=basis)
                record.update(status='APPROVED', decision_ref=basis)
            elif operation in ('promote_finding', 'delete_finding'):
                finding = next((f for f in state['findings'] if f['finding_id'] == args['finding_id']), None)
                if not finding or finding['status'] != 'OPEN':
                    raise PolicyError('FINDING_NOT_OPEN')
                if operation == 'promote_finding':
                    if m['active_run']:
                        raise PolicyError('RUN_ACTIVE')
                    add_nodes(m, [args['node']], self.store.source, approval=basis)
                    finding.update(status='PROMOTED', promoted_node_id=args['node']['id'])
                else:
                    finding['status'] = 'DELETED'
                finding['decision_ref'] = basis
            elif operation in ('defer_requirement', 'restore_requirement'):
                ref = args['requirement_id']
                if ref not in {r['id'] for r in self.store.source['requirements']}:
                    raise PolicyError('UNKNOWN_REQUIREMENT')
                records = m['deferred_requirements']
                present = next((r for r in records if r['requirement_id'] == ref), None)
                if operation == 'defer_requirement':
                    if present:
                        raise PolicyError('ALREADY_DEFERRED')
                    records.append({'requirement_id': ref, 'decision_ref': basis})
                else:
                    if not present:
                        raise PolicyError('NOT_DEFERRED')
                    records.remove(present)
            else:
                raise PolicyError('UNKNOWN_MK_OPERATION')
        return self.store.transact('MK', operation, basis, reduce, expected_revision=expected_revision)

    def submit_proposal(self, raw, *, proposal_id, run_id):
        folder = archive_raw(self.store, raw, proposal_id)
        def reduce(state):
            proposal = parse_message(raw, 'm3_plan_proposal')
            validate_proposal(proposal, state['map'], self.store.source, fixture_mode=self.store.fixture_mode)
            if any(p['id'] == proposal_id for p in state['proposals']):
                raise PolicyError('DUPLICATE_PROPOSAL')
            state['proposals'].append({'id': proposal_id, 'run_id': run_id,
                'sha256': digest(proposal), 'proposal': proposal, 'status': 'PENDING_MK', 'decision_ref': None})
        try:
            return self.store.transact('PLANNER', 'submit_proposal', run_id, reduce)
        except Exception as error:
            (folder / 'parse-error.txt').write_text(str(error), encoding='utf-8')
            raise

    def execute(self, node_id, task, runner, repository_factory, executor_factory, *, basis):
        try:
            return self._execute(node_id, task, runner, repository_factory, executor_factory, basis=basis)
        except Exception as error:
            def rejected(state):
                raise PolicyError(str(error))
            try:
                self.store.transact('MK', 'execute_rejected', basis, rejected)
            except Exception:
                pass  # A corrupt store must remain closed; never fabricate a replacement history.
            raise

    def _execute(self, node_id, task, runner, repository_factory, executor_factory, *, basis):
        if type(runner) is not Runner:
            raise PolicyError('REAL_RUNNER_REQUIRED')
        state = self.store.read(); m = state['map']; node = nodes_by_id(m).get(node_id)
        if not node or node['type'] != 'ATOMIC' or node['status'] != 'READY':
            raise PolicyError('READY_ATOMIC_REQUIRED')
        if m['active_run'] or m['focus'] != node['parent_id']:
            raise PolicyError('EXPLICIT_PARENT_FOCUS_REQUIRED')
        if set(node['requirement_refs']) != set(task['requirement_refs']):
            raise PolicyError('TASK_NODE_SOURCE_MISMATCH')
        for ref in task['requirement_refs']:
            expected = next(r for r in self.store.source['requirements'] if r['id'] == ref)
            actual = next((r for r in runner.source['requirements'] if r['id'] == ref), None)
            if actual != expected:
                raise PolicyError('RUNNER_SOURCE_MISMATCH')
        validate_admission(task, runner.source, runner.records, runner.test_root, fixture_mode=runner.fixture_mode)
        run_id = f'{node_id}-{m["revision"] + 1}'
        evidence = self.store.root / 'runs' / run_id
        if evidence.exists():
            raise PolicyError('RUN_ID_ALREADY_USED')
        evidence.mkdir(parents=True)
        first_repo = repository_factory(1)
        bound = binding(node_id, task, self.controller_root, self.store.root, first_repo)
        write_json(evidence / 'binding.json', bound)
        def start(s):
            sm = s['map']; n = nodes_by_id(sm)[node_id]
            if n['status'] != 'READY' or sm['active_run'] or sm['focus'] != n['parent_id']:
                raise PolicyError('START_CONFLICT')
            n['status'] = 'RUNNING'; sm['focus'] = node_id
            sm['active_run'] = {'node_id': node_id, 'run_id': run_id, 'task_sha256': digest(task), 'stop_target': None}
        self.store.transact('MK', 'start', basis, start, expected_revision=m['revision'])
        original_evidence = runner.evidence_root
        runner.evidence_root = evidence / 'runner'
        executors = []
        protected_before_run = protected_snapshot(self.controller_root, self.store.root)
        def factory(number, prompt):
            if self.store.read()['map']['active_run']['stop_target'] is not None:
                raise PolicyError('MK_STOP_REQUESTED')
            raw_executor = executor_factory(number, prompt)
            executors.append(raw_executor)
            def guarded(repo):
                binding(node_id, task, self.controller_root, self.store.root, repo)
                # A real Codex adapter must carry the extra denial; never trust a caller's prompt.
                from .codex_executor import CodexExecutor
                if isinstance(raw_executor, CodexExecutor):
                    if self.store.root not in raw_executor.protected_resources:
                        raise PolicyError('EXECUTOR_STATE_DENIAL_MISSING')
                before = protected_snapshot(self.controller_root, self.store.root)
                try:
                    raw_executor(repo)
                finally:
                    if protected_snapshot(self.controller_root, self.store.root) != before:
                        raise PolicyError('PROTECTED_CONTROLLER_OR_STATE_CHANGED')
            return guarded
        try:
            result = run_attempts(task, runner, lambda n: first_repo if n == 1 else repository_factory(n), factory, evidence)
            stopped = self.store.read()['map']['active_run']['stop_target']
            if stopped is None and protected_snapshot(self.controller_root, self.store.root) != protected_before_run:
                raise PolicyError('PROTECTED_MATERIAL_CHANGED_DURING_VERIFICATION')
            # The entire M2 retry loop stays in one RUNNING. Only its final result transitions.
            for number, executor in enumerate(executors, 1):
                raw = getattr(executor, 'findings_message', None)
                if raw is not None:
                    try:
                        ingest(self.store, raw, node_id=node_id, run_id=run_id,
                               submission_id=f'{run_id}-finding-{number}')
                    except Exception:
                        pass  # Original message and parse error are archived; no inference.
            final = result['attempts'][-1]
            audit_path = Path(final['audit']) / 'audit.json'
            from .m0 import read_json, validate_report
            audit = read_json(audit_path)
            report = audit['report']
            if report is not None:
                validate_report(task, report, expected_revision=report['revision'])
            success = (report is not None and report['task_id'] == task['task_id'] and
                       report['gate']['status'] == 'PASS' and final['report'] == report)
            def finish(s):
                sm = s['map']
                if {k:v for k,v in sm['active_run'].items() if k != 'stop_target'} != {'node_id': node_id, 'run_id': run_id, 'task_sha256': digest(task)}:
                    raise PolicyError('ACTIVE_RUN_BINDING_CHANGED')
                n = nodes_by_id(sm)[node_id]
                requested_stop = sm['active_run']['stop_target']
                n['status'] = requested_stop or ('DONE' if success else 'BLOCKED')
                sm['active_run'] = None
                if n['status'] in ('DONE','DEFERRED'):
                    sm['focus'] = n['parent_id']
            self.store.transact('CONTROL', 'runner_final', f'{run_id}:{digest(audit)}', finish)
            return result
        except Exception as error:
            # No caller-supplied PASS can reach this path. A failed finalization stays blocked.
            def abort(s):
                if s['map']['active_run'] and s['map']['active_run']['run_id'] == run_id:
                    target = s['map']['active_run']['stop_target'] or 'BLOCKED'
                    n = nodes_by_id(s['map'])[node_id]
                    n['status'] = target
                    s['map']['active_run'] = None
                    if target == 'DEFERRED':
                        s['map']['focus'] = n['parent_id']
            self.store.transact('CONTROL', 'run_aborted', f'{run_id}:{type(error).__name__}', abort)
            raise
        finally:
            runner.evidence_root = original_evidence
