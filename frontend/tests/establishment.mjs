/** Verify one production build with several runtime names; no backend or database is used. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { test } from 'node:test';
import { chromium } from 'playwright';

/** Start the production handler on an operating-system-assigned port. */
async function startFrontend(name) {
	const env = { ...process.env, ORIGIN: 'http://localhost:3000', NODE_ENV: 'production' };
	delete env.ESTABLISHMENT_NAME;
	if (name !== undefined) env.ESTABLISHMENT_NAME = name;
	const child = spawn(
		process.execPath,
		[
			'--input-type=module',
			'-e',
			"import { createServer } from 'node:http'; import { handler } from './build/handler.js'; const server = createServer(handler); server.listen(0, '127.0.0.1', () => console.log('PORT=' + server.address().port));"
		],
		{
			cwd: new URL('..', import.meta.url),
			env,
			windowsHide: true,
			stdio: ['ignore', 'pipe', 'pipe']
		}
	);
	let output = '';
	child.stderr.on('data', (chunk) => (output += chunk));
	try {
		const base = await new Promise((resolve, reject) => {
			const timer = setTimeout(() => reject(new Error('Frontend startup timed out')), 15000);
			child.once('error', reject);
			child.once('exit', (code) => {
				clearTimeout(timer);
				reject(new Error(`Frontend exited (${code}): ${output}`));
			});
			child.stdout.on('data', (chunk) => {
				output += chunk;
				const port = output.match(/PORT=(\d+)/)?.[1];
				if (port) {
					clearTimeout(timer);
					resolve(`http://127.0.0.1:${port}`);
				}
			});
		});
		return {
			base,
			async stop() {
				const exited = once(child, 'exit');
				child.kill();
				await exited;
			}
		};
	} catch (cause) {
		child.kill();
		throw cause;
	}
}

test('one production build renders different runtime names and escapes HTML in text and metadata', async () => {
	for (const [configured, expected] of [
		[undefined, 'Sophikron'],
		[' \t ', 'Sophikron'],
		['  Lycée Jean Moulin  ', 'Lycée Jean Moulin'],
		[
			'École d’Art & "Sciences" <script>alert(1)</script>',
			'École d’Art & "Sciences" <script>alert(1)</script>'
		]
	]) {
		const server = await startFrontend(configured);
		try {
			const escapedText = expected.replaceAll('&', '&amp;').replaceAll('<', '&lt;');
			const escapedAttribute = escapedText.replaceAll('"', '&quot;');
			for (const [path, title, status] of [
				['/', `${escapedText} — Apprendre, ensemble`, 200],
				['/login', `Connexion — ${escapedText}`, 200],
				['/activate', `Définir mon mot de passe — ${escapedText}`, 200],
				['/missing-establishment-test', `Erreur 404 — ${escapedText}`, 404]
			]) {
				const response = await fetch(server.base + path);
				const html = await response.text();
				assert.equal(response.status, status, path);
				assert.ok(
					html.includes(`<title>${title}</title>`),
					`${path}: ${html.match(/<title>.*?<\/title>/)?.[0]}`
				);
				assert.ok(
					html.includes(`<strong>${escapedText}</strong>`),
					`${path}: ${html.match(/<strong>.*?<\/strong>/)?.[0]}`
				);
				assert.ok(
					html.includes(`aria-label="${escapedAttribute}, accueil"`),
					`${path}: ${html.match(/aria-label="[^"]*, accueil"/)?.[0]}`
				);
				assert.ok(!html.includes('<script>alert(1)</script>'), path);
				if (expected !== 'Sophikron') assert.ok(!html.includes('Sophikron'), path);
				if (path === '/')
					assert.ok(html.includes(`content="${escapedAttribute} — Apprendre, ensemble"`));
			}
		} finally {
			await server.stop();
		}
	}
});

test('a long establishment name fits mobile navigation and survives browser navigation', async () => {
	const name = 'Établissement des arts et sciences ' + 'Pédagogie'.repeat(12);
	const server = await startFrontend(name);
	let browser;
	try {
		browser = await chromium.launch({
			channel: process.env.BFF_BROWSER_CHANNEL || 'msedge',
			headless: true
		});
		const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
		await page.goto(server.base);
		await page.getByRole('link', { name: 'Se connecter' }).click();
		await page.waitForURL('**/login');
		assert.equal(await page.title(), `Connexion — ${name}`);
		assert.equal(await page.locator('.brand-name').textContent(), name);
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
	} finally {
		await browser?.close();
		await server.stop();
	}
});
