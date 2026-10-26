/** Verify one production build with several runtime names; no backend or database is used. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { test } from 'node:test';
import { chromium } from 'playwright';
import { createServer } from 'node:http';

/** Start the production handler on an operating-system-assigned port. */
async function startFrontend(name) {
	const env = { ...process.env, ORIGIN: 'http://localhost:3000', NODE_ENV: 'production' };
	let currentName = name?.trim() || 'Sophikron';
	const backend = createServer((request, response) => {
		if (request.url !== '/api/v1/site') {
			response.writeHead(404).end();
			return;
		}
		response.setHeader('content-type', 'application/json');
		response.end(
			JSON.stringify({
				settings: {
					name: currentName,
					home_text: '# Bienvenue\n**Bonjour** <script>alert(1)</script>',
					text_color: '#244BC1',
					version: 0
				},
				timelines: [],
				events: [],
				today: '2026-10-25'
			})
		);
	});
	await new Promise((resolve) => backend.listen(0, '127.0.0.1', resolve));
	env.BACKEND_ORIGIN = `http://127.0.0.1:${backend.address().port}`;
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
			setName(value) {
				currentName = value;
			},
			async stop() {
				const exited = once(child, 'exit');
				child.kill();
				await exited;
				await new Promise((resolve) => backend.close(resolve));
			}
		};
	} catch (cause) {
		child.kill();
		backend.close();
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
			server.setName('Nouveau nom');
			assert.ok(
				(await (await fetch(server.base)).text()).includes(
					'<title>Nouveau nom — Apprendre, ensemble</title>'
				)
			);
			await server.stop();
		}
	}
});

test('a long establishment name fits mobile navigation and survives browser navigation', async () => {
	const name = 'Établissement des arts et sciences ' + 'Pédagogie'.repeat(6);
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

test('missing pages retain HTTP 404 and hydrate one of the three cat messages', async () => {
	const server = await startFrontend('Lycée des chats');
	let browser;
	try {
		browser = await chromium.launch({ channel: process.env.BFF_BROWSER_CHANNEL || 'msedge' });
		const page = await browser.newPage({
			viewport: { width: 375, height: 812 },
			colorScheme: 'dark'
		});
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		page.on('console', (message) => {
			if (/hydration/i.test(message.text())) errors.push(message.text());
		});
		await page.addInitScript(() => {
			Math.random = () => 0.99;
		});
		const response = await page.goto(`${server.base}/this-cat-page-does-not-exist`);
		assert.equal(response.status(), 404);
		assert.match(await response.text(), /Cette page a filé entre les pattes\./);
		await page
			.getByText('Même le chat sèche. Et pourtant, il a neuf vies pour chercher.', {
				exact: true
			})
			.waitFor();
		assert.equal(await page.title(), 'Erreur 404 — Lycée des chats');
		const image = page.getByRole('img', { name: /Un chat tricolore/ });
		await image.evaluate((element) => element.decode());
		assert.ok(await image.evaluate((element) => element.naturalWidth > 0));
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		await page.getByRole('link', { name: 'Retour à l’accueil', exact: true }).click();
		await page.waitForURL(server.base + '/');
		assert.equal(await page.locator('.not-found').count(), 0);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.stop();
	}
});
