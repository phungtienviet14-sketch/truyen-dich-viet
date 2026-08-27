'use strict';
const { copyFileSync, mkdirSync } = require('node:fs');
const { join } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = join(__dirname, '..');
mkdirSync(join(root, 'app/static/css'), { recursive: true });
mkdirSync(join(root, 'app/static/js'), { recursive: true });
execFileSync(process.execPath, [
    require.resolve('tailwindcss/lib/cli.js'),
    '-c', 'tailwind.config.cjs', '-i', 'app/static/css/input.css',
    '-o', 'app/static/css/app.css', '--minify',
], { cwd: root, stdio: 'inherit' });
copyFileSync(require.resolve('lucide/dist/umd/lucide.min.js'), join(root, 'app/static/js/lucide.min.js'));
