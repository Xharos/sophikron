import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import type { AddressInfo } from 'node:net';

const browser = [
	process.env.BROWSER_EXECUTABLE,
	'C:/Program Files/Google/Chrome/Application/chrome.exe',
	'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
	'/usr/bin/google-chrome',
	'/usr/bin/chromium'
].find((path): path is string => !!path && existsSync(path));

test(
	'the production referrer policy preserves Origin on a native browser form POST',
	{ skip: !browser, timeout: 30000 },
	async () => {
		const hooks = await readFile(new URL('../src/hooks.server.ts', import.meta.url), 'utf8');
		const policy = hooks.match(/set\('Referrer-Policy', '([^']+)'\)/)?.[1];
		assert.ok(policy, 'The application must define an explicit referrer policy');
		const profile = await mkdtemp(join(tmpdir(), 'sophikron-origin-'));
		const target = resolve(profile);
		assert.ok(
			target.startsWith(resolve(tmpdir()) + sep) &&
				target.split(sep).at(-1)?.startsWith('sophikron-origin-'),
			'Unexpected temporary browser profile path'
		);
		let received: string | undefined;
		const server = createServer((request, response) => {
			response.setHeader('Referrer-Policy', policy);
			response.setHeader('Content-Type', 'text/html');
			if (request.method === 'POST') {
				received = request.headers.origin;
				response.end('<p>Submitted</p>');
			} else {
				response.end(
					'<form method="POST" action="/logout"><button type="submit">Logout</button></form><script>document.querySelector("button").click()</script>'
				);
			}
		});
		await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
		try {
			const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
			const child = spawn(
				browser!,
				[
					'--headless=new',
					'--disable-background-networking',
					'--disable-extensions',
					'--no-first-run',
					`--user-data-dir=${profile}`,
					'--dump-dom',
					'--virtual-time-budget=2000',
					origin
				],
				{ windowsHide: true, stdio: 'ignore', signal: AbortSignal.timeout(15000) }
			);
			await new Promise<void>((done, reject) => {
				child.on('exit', () => done());
				child.on('error', reject);
			});
			assert.equal(received, origin, 'Native forms must send their actual origin, never null');
		} finally {
			await new Promise<void>((done) => server.close(() => done()));
			await rm(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
		}
	}
);
