// Bundle exactly the locally built wheel; installation never fetches application code from PyPI.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const wheel = 'release_workbench-0.18.1-py3-none-any.whl';
const bytes = fs.readFileSync(path.join(root, 'dist', wheel));
const runtime = path.resolve(__dirname, '../runtime');
fs.rmSync(runtime, { recursive: true, force: true });
fs.mkdirSync(runtime, { recursive: true });
fs.copyFileSync(path.join(root, 'LICENSE'), path.resolve(__dirname, '../LICENSE'));
fs.writeFileSync(path.join(runtime, wheel), bytes);
fs.writeFileSync(path.join(runtime, 'manifest.json'), JSON.stringify({ wheel, sha256: crypto.createHash('sha256').update(bytes).digest('hex') }, null, 2));
console.log('Bundled wheel and SHA-256 for npm distribution.');
