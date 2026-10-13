const { spawn } = require('node:child_process');

const python = process.env.BOOSTUDY_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const port = process.env.PORT || '5000';
const env = { ...process.env, SECRET_KEY: process.env.SECRET_KEY || 'boostudy-e2e-secret' };
const args = ['-c', `from wsgi import app; app.run(host='127.0.0.1', port=${Number(port)}, debug=False, use_reloader=False)`];
const child = spawn(python, args, { env, stdio: 'inherit', cwd: process.cwd() });
child.on('error', (error) => { console.error(`Unable to start Python server with ${python}:`, error); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
process.on('SIGINT', () => child.kill('SIGINT'));
process.on('SIGTERM', () => child.kill('SIGTERM'));
