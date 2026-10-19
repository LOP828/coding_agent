"""Human-readable projection of controller records, without semantic judgement."""
from .m0 import read_json
from .task_map import completable, uncovered


def render(store):
    state = store.read(); m = state['map']
    lines = [f"主线/目标：{m['goal']}", f"当前焦点：{m['focus'] or '无'}", '', '节点：']
    for n in m['nodes']:
        suffix = '（可完成，等待 MK 确认）' if completable(m, n) else ''
        lines.append(f"- {n['id']} | 父：{n['parent_id']} | {n['status']}{suffix} | {n['title']}")
    lines += ['', '暂存区：']
    lines += [f"- {f['finding_id']} | {f['status']} | {f['content']}" for f in state['findings'] if f['status'] != 'DELETED'] or ['- 无']
    lines += ['', '待 MK 决策：']
    decisions = [f"- 提案 {p['id']}：{p['status']}；哈希 {p['sha256']}" for p in state['proposals'] if p['status'] == 'PENDING_MK']
    decisions += [f"- 节点 {n['id']}：{n['status']}" for n in m['nodes'] if n['status'] == 'BLOCKED' or completable(m, n)]
    decisions += [f"- 发现 {f['finding_id']}：等待提升或删除" for f in state['findings'] if f['status'] == 'OPEN']
    for path in sorted((store.root / 'runs').glob('*/prepared-request.json')):
        request = read_json(path)
        if request.get('status') == 'AWAITING_MK_PROMPT_AND_PARAMETER_APPROVAL' and not (path.parent / 'execution.json').exists():
            decisions.append(f'- 真实规划 {path.parent.name}：等待 MK 确认完整提示词与调用参数')
    lines += decisions or ['- 无']
    lines += ['', 'MK 不批准的提案（原文保留）：']
    lines += [f"- {p['id']}：{p['status']}；依据：{p['decision_ref']}"
              for p in state['proposals'] if p['status'] == 'REJECTED'] or ['- 无']
    lines += ['', '待 MK 澄清的问题：']
    questions = [f"- 提案 {p['id']} / {','.join(q['requirement_refs'])}：{q['question']}"
                 for p in state['proposals'] if p['status'] == 'PENDING_MK' for q in p['proposal']['questions_for_mk']]
    lines += questions or ['- 无']
    lines += ['', '未覆盖冻结需求（仅结构检查）：']
    lines += [f'- {r}' for r in uncovered(m, store.source)] or ['- 无']
    return '\n'.join(lines) + '\n'
