import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'node:http';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import type { AddressInfo } from 'node:net';
import { chromium } from 'playwright';

const browser = [
	process.env.BROWSER_EXECUTABLE,
	chromium.executablePath(),
	'C:/Program Files/Google/Chrome/Application/chrome.exe',
	'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
	'/usr/bin/google-chrome',
	'/usr/bin/chromium'
].find((path): path is string => !!path && existsSync(path));

test(
	'the production referrer policy preserves Origin on a native browser form POST',
	{ skip: !browser && !process.env.CI, timeout: 30000 },
	async () => {
		assert.ok(browser, 'Install Chromium with npx playwright install chromium');
		const hooks = await readFile(new URL('../src/hooks.server.ts', import.meta.url), 'utf8');
		const policy = hooks.match(/set\('Referrer-Policy', '([^']+)'\)/)?.[1];
		assert.ok(policy, 'The application must define an explicit referrer policy');
		let received: string | undefined;
		const server = createServer((request, response) => {
			response.setHeader('Referrer-Policy', policy);
			response.setHeader('Content-Type', 'text/html');
			if (request.method === 'POST') {
				received = request.headers.origin;
				response.end('<p>Submitted</p>');
			} else {
				response.end(
					'<form method="POST" action="/logout"><button type="submit">Logout</button></form>'
				);
			}
		});
		await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
		try {
			const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
			const instance = await chromium.launch({
				executablePath: browser,
				headless: true,
				timeout: 10000
			});
			try {
				const page = await instance.newPage();
				page.setDefaultTimeout(10000);
				await page.goto(origin);
				await Promise.all([
					page.waitForResponse(
						(response) =>
							response.url() === `${origin}/logout` && response.request().method() === 'POST'
					),
					page.getByRole('button', { name: 'Logout' }).click()
				]);
				assert.equal(received, origin, 'Native forms must send their actual origin, never null');
			} finally {
				await instance.close();
			}
		} finally {
			await new Promise<void>((done) => server.close(() => done()));
		}
	}
);
