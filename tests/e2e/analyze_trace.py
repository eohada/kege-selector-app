import json
import sys

trace_path = sys.argv[1] if len(sys.argv) > 1 else "docs/audits/boostudy-os-reliability/artifacts/sprint10_perf/trace_H_stroke_draw.json"

with open(trace_path, "r", encoding="utf-8") as f:
    data = json.load(f)

events = data.get("traceEvents", [])
durations = {}
counts = {}

for e in events:
    dur = e.get("dur", 0)
    name = e.get("name", "unknown")
    if dur > 0:
        durations[name] = durations.get(name, 0) + dur
        counts[name] = counts.get(name, 0) + 1

print(f"=== TOP 20 TIME-CONSUMING TRACE EVENTS in {trace_path} ===")
print(f"{'Event Name':35} | {'Count':6} | {'Total (ms)':10} | {'Avg (ms)':8}")
print("-" * 65)

top = sorted(durations.items(), key=lambda x: x[1], reverse=True)[:20]
for name, total_dur_us in top:
    cnt = counts[name]
    total_ms = total_dur_us / 1000.0
    avg_ms = total_ms / cnt
    print(f"{name:35} | {cnt:6} | {total_ms:10.2f} | {avg_ms:8.2f}")
