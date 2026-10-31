import json

with open("docs/audits/boostudy-os-reliability/artifacts/sprint10_perf/baseline_benchmark_results.json") as f:
    base = json.load(f)
with open("docs/audits/boostudy-os-reliability/artifacts/sprint10_perf/optimized_benchmark_results.json") as f:
    opt = json.load(f)

headers = ["Scenario", "Base FPS", "Opt FPS", "Base p50", "Opt p50", "Base p95", "Opt p95", "Base 1%", "Opt 1%", "Base MaxLT", "Opt MaxLT"]
row_fmt = "{:<25} | {:<8} | {:<8} | {:<8} | {:<8} | {:<8} | {:<8} | {:<8} | {:<8} | {:<10} | {:<10}"
print(row_fmt.format(*headers))
print("-" * 125)

for k in base:
    b = base.get(k, {})
    o = opt.get(k, {})
    print(row_fmt.format(
        k,
        b.get("fps", 0), o.get("fps", 0),
        b.get("p50", 0), o.get("p50", 0),
        b.get("p95", 0), o.get("p95", 0),
        b.get("low1Pct", 0), o.get("low1Pct", 0),
        b.get("maxLongTask", 0), o.get("maxLongTask", 0)
    ))
