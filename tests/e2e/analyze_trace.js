const fs = require('fs');
const tracePath = 'docs/audits/boostudy-os-reliability/artifacts/sprint10_perf/trace_diag_drag_monitors.json';
const data = JSON.parse(fs.readFileSync(tracePath, 'utf8'));
const events = data.traceEvents || data;

// Filter events by categories of interest
const jsCalls = events.filter(e => e.name === 'FunctionCall' || e.name === 'EvaluateScript' || e.name === 'v8.callFunction');
console.log('Total JS FunctionCall / EvaluateScript events:', jsCalls.length);

const longJs = jsCalls.filter(e => e.dur && e.dur > 5000).sort((a,b) => b.dur - a.dur);
console.log('JS calls > 5ms:', longJs.length);
longJs.slice(0, 15).forEach((e, idx) => {
  console.log(`${idx + 1}. [${e.name}] ${(e.dur / 1000).toFixed(2)}ms, args:`, JSON.stringify(e.args).slice(0, 200));
});

// Layout & Style Recalc
const layouts = events.filter(e => e.name === 'Layout' || e.name === 'UpdateLayoutTree');
console.log('\nTotal Layout / UpdateLayoutTree events:', layouts.length);
const longLayouts = layouts.filter(e => e.dur && e.dur > 2000).sort((a,b) => b.dur - a.dur);
console.log('Layout events > 2ms:', longLayouts.length);
longLayouts.slice(0, 10).forEach((e, idx) => {
  console.log(`${idx + 1}. [${e.name}] ${(e.dur / 1000).toFixed(2)}ms`);
});

// Paint & Raster
const rasters = events.filter(e => e.name === 'RasterTask' || e.name === 'Paint');
console.log('\nTotal Paint / RasterTask events:', rasters.length);
const longRasters = rasters.filter(e => e.dur && e.dur > 2000).sort((a,b) => b.dur - a.dur);
console.log('Paint/Raster events > 2ms:', longRasters.length);
longRasters.slice(0, 10).forEach((e, idx) => {
  console.log(`${idx + 1}. [${e.name}] ${(e.dur / 1000).toFixed(2)}ms`);
});
