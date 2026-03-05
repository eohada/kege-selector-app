import json, sys, random
sys.stdout.reconfigure(encoding='utf-8')

with open('data/oge_inf_tasks.json', 'r', encoding='utf-8') as f:
    tasks = json.load(f)

generated = [t for t in tasks if t.get('generated')]
print(f"Total: {len(tasks)}, Generated: {len(generated)}")

errors = 0
for tn in range(1, 17):
    group = [t for t in generated if t['task_number'] == tn]
    if not group:
        print(f"  Task {tn}: NO GENERATED TASKS!")
        errors += 1
        continue

    no_answer = [t for t in group if not t.get('answer')]
    no_solution = [t for t in group if not t.get('solution_html')]
    no_diff = [t for t in group if not t.get('difficulty_level')]

    sample = random.choice(group)
    ans = sample.get('answer', '')[:30]
    has_content = len(sample.get('content_html', '')) > 50

    status = 'OK' if has_content else 'BAD'
    if tn not in [13, 15] and len(no_answer) > len(group) * 0.5:
        status = 'WARN: many without answers'

    print(f"  Task {tn:>2}: {len(group):>3} tasks | "
          f"no_ans={len(no_answer):>3} | no_sol={len(no_solution):>3} | "
          f"no_diff={len(no_diff):>3} | {status} | sample_ans='{ans}'")

    if tn <= 10 and group:
        s = random.choice([t for t in group if t.get('answer')] or group)
        print(f"         Example (id={s['site_id']}): answer='{s.get('answer','')[:40]}' "
              f"diff={s.get('difficulty_level','')} "
              f"content[..80]='{s.get('content_html','')[:80]}...'")

print(f"\nTotal errors: {errors}")
