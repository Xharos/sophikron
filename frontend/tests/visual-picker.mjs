import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { createServer } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { chromium } from 'playwright';
import { lessonIcons } from '../src/lib/lessons.ts';
import { themedHtml } from '../src/lib/theme.ts';
import { contrastRatio } from '../src/lib/colors.ts';

function pickerServer() {
	return createServer({
		configFile: false,
		resolve: { alias: { '#lib': resolve('src/lib') } },
		plugins: [
			svelte(),
			{
				name: 'picker-test-page',
				resolveId(id) {
					if (id === '$app/paths') return '\0test-paths';
					if (id === '$app/navigation') return '\0test-navigation';
					if (id === '$app/state') return '\0test-state';
				},
				load(id) {
					if (id === '\0test-paths') return 'export const resolve = (path) => path;';
					if (id === '\0test-navigation')
						return 'export const beforeNavigate = () => {};';
					if (id === '\0test-state')
						return `export const page = {
							url: new URL(window.location.href),
							status: Number(new URL(window.location.href).searchParams.get('status') || 404),
							error: { message: 'Accès refusé.' },
							data: { establishmentName: 'Sophikron' }
						};`;
				},
				configureServer(vite) {
					vite.middlewares.use('/__picker', async (_request, response) => {
						const fixture = _request.url.includes('error')
							? 'ErrorHarness'
							: _request.url.includes('lesson')
								? 'LessonHarness'
								: _request.url.includes('theme')
									? 'ThemeHarness'
									: 'VisualPickerHarness';
						const preference = /(?:^|;\s*)sophikron_theme=([^;]*)/.exec(
							_request.headers.cookie || ''
						)?.[1];
						response.setHeader('Content-Type', 'text/html');
						response.end(
							await vite.transformIndexHtml(
								'/__picker',
								themedHtml(
									`<html lang="fr" data-theme="system"><title>Visual picker test</title><body><div id="app"></div><script type="module">
					import { mount } from 'svelte';
					import Harness from '/tests/fixtures/${fixture}.svelte';
					mount(Harness, {target: document.getElementById('app')});
					</script></body></html>`,
									preference
								)
							)
						);
					});
				}
			}
		],
		server: { host: '127.0.0.1', port: 0, watch: null, hmr: false }
	});
}

test('404 shows only the retained messages and the cat rests its paw while looking around', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.addInitScript(() => {
			const random = Number(new URL(window.location.href).searchParams.get('random'));
			Math.random = () => random;
		});
		const url = `${server.resolvedUrls.local[0]}__picker?error`;
		const messages = [
			'Cette page a filé entre les pattes.',
			'Cette page est partie réviser dans un endroit très discret.',
			'Même le chat sèche. Et pourtant, il a neuf vies pour chercher.'
		];
		for (const colorScheme of ['light', 'dark']) {
			await page.emulateMedia({ colorScheme });
			for (const [index, random] of [0, 0.5, 0.99].entries()) {
				await page.goto(`${url}&random=${random}`);
				await page.getByText(messages[index], { exact: true }).waitFor();
				assert.equal(await page.title(), 'Erreur 404 — Sophikron');
				assert.equal(
					await page.locator('meta[name="robots"]').getAttribute('content'),
					'noindex, nofollow'
				);
				assert.equal(
					await page
						.getByRole('link', { name: 'Retour à l’accueil' })
						.getAttribute('href'),
					'/'
				);
				assert.equal(
					await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
					true
				);
			}
		}
		const image = page.getByRole('img');
		await image.evaluate((element) => element.decode());
		assert.equal(
			await image.evaluate((element) => {
				const canvas = document.createElement('canvas');
				canvas.width = element.naturalWidth;
				canvas.height = element.naturalHeight;
				const context = canvas.getContext('2d');
				context.drawImage(element, 0, 0);
				return context.getImageData(0, 0, 1, 1).data[3];
			}),
			0
		);
		const svgUrl = new URL(await image.getAttribute('src'), page.url()).href;
		await page.goto(`${url}&status=403`);
		await page.getByText('Accès refusé.', { exact: true }).waitFor();
		assert.equal(await page.locator('.not-found').count(), 0);
		assert.equal(await page.title(), 'Erreur 403 — Sophikron');
		await page.goto(svgUrl);
		for (const [time, resting] of [
			[1100, false],
			[5000, true],
			[7300, true],
			[11500, false]
		]) {
			await page.evaluate(
				(time) =>
					document.getAnimations().forEach((animation) => {
						animation.pause();
						animation.currentTime = time;
					}),
				time
			);
			const bottom = await page.locator('.paw-shape').evaluate((element) => {
				const box = element.getBBox();
				return box.y + box.height;
			});
			assert.ok(resting ? bottom >= 300 : bottom < 250, `Paw pose at ${time}ms: ${bottom}`);
			assert.equal(
				await page
					.locator('.licking')
					.evaluate((element) => getComputedStyle(element).opacity),
				resting ? '0' : '1'
			);
		}
		await page.emulateMedia({ reducedMotion: 'reduce' });
		for (const selector of [
			'.head',
			'.paw-shape',
			'.paw-toes',
			'.face',
			'.licking',
			'.tongue'
		]) {
			assert.equal(
				await page
					.locator(selector)
					.first()
					.evaluate((element) => getComputedStyle(element).animationName),
				'none'
			);
		}
		assert.ok(
			await page
				.locator('.paw-shape')
				.evaluate((element) => element.getBBox().y + element.getBBox().height >= 300)
		);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('theme follows the device, persists overrides and keeps colored controls readable', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const context = await browser.newContext({
			colorScheme: 'dark',
			reducedMotion: 'reduce',
			viewport: { width: 390, height: 844 }
		});
		const page = await context.newPage();
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		const url = `${server.resolvedUrls.local[0]}__picker?theme`;
		await page.goto(url);
		const picker = page.getByRole('group', { name: 'Apparence', exact: true });
		await picker
			.getByRole('radio', { name: 'Périphérique', exact: true })
			.waitFor({ state: 'attached' });
		const background = () =>
			page.locator('html').evaluate((element) => getComputedStyle(element).backgroundColor);
		const dark = await background();
		assert.equal(
			await picker.getByRole('radio', { name: 'Périphérique', exact: true }).isChecked(),
			true
		);
		await page.emulateMedia({ colorScheme: 'light' });
		const light = await background();
		assert.notEqual(light, dark);
		await picker.getByText('Sombre', { exact: true }).click();
		assert.equal(await background(), dark);
		assert.equal(
			(await context.cookies()).find((cookie) => cookie.name === 'sophikron_theme').value,
			'dark'
		);
		const response = await page.reload();
		assert.match(await response.text(), /data-theme="dark"/);
		await picker
			.getByRole('radio', { name: 'Sombre', exact: true })
			.waitFor({ state: 'attached' });
		assert.equal(await background(), dark);
		await page.emulateMedia({ colorScheme: 'dark' });
		await picker.getByText('Clair', { exact: true }).click();
		assert.equal(await background(), light);
		await picker.getByRole('radio', { name: 'Clair', exact: true }).focus();
		await page.keyboard.press('ArrowRight');
		assert.equal(await background(), dark);
		assert.equal(
			(await context.cookies()).find((cookie) => cookie.name === 'sophikron_theme').value,
			'system'
		);
		await page.emulateMedia({ colorScheme: 'light' });
		assert.equal(await background(), light);
		for (const scheme of ['light', 'dark']) {
			await page.emulateMedia({ colorScheme: scheme });
			const failures = await page.evaluate(() => {
				const canvas = document.createElement('canvas');
				canvas.width = canvas.height = 1;
				const context = canvas.getContext('2d', { willReadFrequently: true });
				function rgba(color) {
					context.clearRect(0, 0, 1, 1);
					context.fillStyle = color;
					context.fillRect(0, 0, 1, 1);
					return [...context.getImageData(0, 0, 1, 1).data];
				}
				function backdrop(element) {
					if (!element) return [255, 255, 255];
					const background = rgba(getComputedStyle(element).backgroundColor);
					const alpha = background[3] / 255;
					const below = alpha === 1 ? background : backdrop(element.parentElement);
					return background
						.slice(0, 3)
						.map((channel, index) => channel * alpha + below[index] * (1 - alpha));
				}
				function luminance(rgb) {
					return rgb
						.slice(0, 3)
						.map((value) => {
							value /= 255;
							return value <= 0.04045
								? value / 12.92
								: ((value + 0.055) / 1.055) ** 2.4;
						})
						.reduce(
							(sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index],
							0
						);
				}
				return [
					...document.querySelectorAll(
						'.tag.is-light, .role-badge, .subject-badge, .tag-choice, .colored, .theme-track label, .muted, .notification, .account-status, .button, .choice-icon, .table th, .table td, .input, .select select, .timeline-months > span > span, .chart-legend button, svg polyline'
					)
				].flatMap((element) => {
					const foreground = rgba(
						element.tagName === 'polyline'
							? getComputedStyle(element).stroke
							: getComputedStyle(element).color
					);
					const values = [luminance(foreground), luminance(backdrop(element))].sort(
						(a, b) => b - a
					);
					const ratio = (values[0] + 0.05) / (values[1] + 0.05);
					return ratio >= 4.5
						? []
						: [{ element: element.className, text: element.textContent.trim(), ratio }];
				});
			});
			assert.deepEqual(failures, [], `Text/icon contrast in ${scheme}`);
			if (process.env.THEME_PREVIEW)
				await page.screenshot({
					path: `.svelte-kit/theme-${scheme}-preview.png`,
					fullPage: true
				});
			assert.equal(
				await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
				true
			);
		}
		await page.setViewportSize({ width: 1440, height: 1000 });
		assert.equal(
			await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
			true
		);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('course cards, folded sections, locked resources and file drop forms stay usable in both themes', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({
			viewport: { width: 390, height: 844 },
			reducedMotion: 'reduce'
		});
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.route('**/lessons/options?resource=documentLimits', (route) =>
			route.fulfill({ json: { types: { pdf: 26214400, py: 1048576 } } })
		);
		await page.goto(`${server.resolvedUrls.local[0]}__picker?lesson`);
		await page.getByRole('heading', { name: 'Algèbre et applications' }).waitFor();
		assert.equal(await page.getByText('Créateur historique').count(), 0);
		assert.equal(await page.getByText('Administrateur', { exact: true }).count(), 0);
		assert.deepEqual(
			await page
				.locator('.team-line')
				.allTextContents()
				.then((lines) => lines.map((line) => line.replace(/\s+/g, ' ').trim())),
			['Camille Martin Alice Durand', 'Zoé Bernard']
		);
		assert.ok((await page.locator('.course-card').boundingBox()).height < 300);
		const arrow = await page.locator('.course-open').boundingBox();
		assert.equal(arrow.width, arrow.height);
		const section = page.getByRole('button', { name: 'Chapitre un', exact: true });
		assert.equal(await section.getAttribute('aria-expanded'), 'false');
		await section.click();
		assert.equal(
			await page.getByText('Le contenu pédagogique reste toujours visible.').isVisible(),
			true
		);
		assert.equal(await page.locator('.resource-card.unavailable').count(), 2);
		assert.equal(
			await page
				.locator('.resource-card.unavailable a, .resource-card.unavailable button')
				.count(),
			0
		);
		assert.equal(await page.locator('iframe').count(), 0);
		assert.equal(await page.getByText('2029', { exact: false }).count(), 0);
		assert.equal(await page.getByText('Équipe seulement').count(), 0);
		await page.getByRole('button', { name: 'Approfondissement', exact: true }).click();
		assert.equal(await page.getByText('Contenu de la sous-section.').isVisible(), false);
		await page.getByRole('button', { name: 'Approfondissement', exact: true }).press('Enter');
		assert.equal(await page.getByText('Contenu de la sous-section.').isVisible(), true);
		await page.getByRole('button', { name: 'Déposer un document', exact: true }).click();
		const dialog = page.getByRole('dialog');
		await dialog.locator('input[type=file]').waitFor({ state: 'attached' });
		await dialog.getByRole('group', { name: 'Dépôt de document' }).dispatchEvent('drop', {
			dataTransfer: await page.evaluateHandle(() => {
				const transfer = new DataTransfer();
				transfer.items.add(
					new File(['%PDF-fixture'], 'Chapitre.1.pdf', { type: 'application/pdf' })
				);
				return transfer;
			})
		});
		assert.equal(
			await dialog.getByLabel('Nom affiché dans le cours').inputValue(),
			'Chapitre.1'
		);
		await dialog.locator('input[type=file]').setInputFiles({
			name: 'Chapitre.2.pdf',
			mimeType: 'application/pdf',
			buffer: Buffer.from('%PDF-fixture')
		});
		assert.equal(
			await dialog.getByLabel('Nom affiché dans le cours').inputValue(),
			'Chapitre.2'
		);
		assert.equal(
			await dialog.getByRole('combobox', { name: 'Disponibilité', exact: true }).count(),
			1
		);
		page.once('dialog', (confirmation) => confirmation.accept());
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		await page.getByRole('button', { name: 'Document équipe', exact: true }).click();
		assert.equal(await dialog.getByRole('combobox').count(), 0);
		assert.equal(await dialog.getByText('Visibilité', { exact: true }).count(), 0);
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		await page.getByRole('button', { name: 'Changer de vue', exact: true }).click();
		assert.equal(await page.getByText('Équipe seulement').isVisible(), true);
		assert.equal(await page.getByRole('link', { name: 'Télécharger Exercices' }).count(), 1);
		for (const colorScheme of ['light', 'dark']) {
			await page.emulateMedia({ colorScheme });
			await page.evaluate(
				() =>
					new Promise((resolve) =>
						requestAnimationFrame(() => requestAnimationFrame(resolve))
					)
			);
			const colors = await page
				.locator(
					'.course-identity h2 a, .section-toggle, .resource-card, .resource-label strong, .resource-label small, .button.is-light, .icon-button:not(:disabled)'
				)
				.evaluateAll((elements) => {
					const context = document
						.createElement('canvas')
						.getContext('2d', { willReadFrequently: true });
					function rgba(color) {
						context.clearRect(0, 0, 1, 1);
						context.fillStyle = color;
						context.fillRect(0, 0, 1, 1);
						return [...context.getImageData(0, 0, 1, 1).data];
					}
					function hex(color) {
						return (
							'#' +
							color
								.slice(0, 3)
								.map((channel) => channel.toString(16).padStart(2, '0'))
								.join('')
						);
					}
					return elements.map((element) => {
						let ancestor = element;
						while (
							ancestor.parentElement &&
							rgba(getComputedStyle(ancestor).backgroundColor)[3] === 0
						)
							ancestor = ancestor.parentElement;
						return {
							foreground: hex(rgba(getComputedStyle(element).color)),
							background: hex(rgba(getComputedStyle(ancestor).backgroundColor)),
							text: element.textContent.trim()
						};
					});
				});
			assert.deepEqual(
				colors.filter((item) => contrastRatio(item.foreground, item.background) < 4.5),
				[],
				colorScheme
			);
			assert.equal(
				await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
				true
			);
			if (process.env.THEME_PREVIEW)
				await page.screenshot({
					path: `.svelte-kit/lessons-${colorScheme}-preview.png`,
					fullPage: true
				});
		}
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('collaborator suggestions open immediately, search each letter and refill after adding', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		const people = Array.from({ length: 7 }, (_, index) => ({
			id: 20 + index,
			label: `Alex Martin ${index + 1}`,
			role: index % 2 ? 'kholleur' : 'teacher',
			can_edit: index % 2 === 0
		}));
		const added = new Set();
		const requests = [];
		await page.route('**/lessons/options?*', async (route) => {
			const url = new URL(route.request().url());
			if (url.searchParams.get('resource') !== 'teachers') return route.fulfill({ json: [] });
			const q = url.searchParams.get('q') || '';
			requests.push(q);
			const matches = people
				.filter(
					(person) =>
						!added.has(person.id) &&
						person.label.toLowerCase().includes(q.toLowerCase())
				)
				.slice(0, 5);
			await route.fulfill({ json: matches });
		});
		await page.route('**/lessons/command', async (route) => {
			const data = route.request().postDataJSON();
			assert.equal(data.command, 'addCollaborator');
			added.add(data.userId);
			await route.fulfill({
				json: {
					version: added.size,
					collaborators: people.filter((person) => added.has(person.id))
				}
			});
		});
		await page.goto(`${server.resolvedUrls.local[0]}__picker?lesson`);
		await page.getByRole('button', { name: 'Gérer les collaborateurs', exact: true }).click();
		const dialog = page.getByRole('dialog');
		const list = dialog.locator('#collaborator-candidates');
		await list.locator('.candidate-row').nth(4).waitFor();
		assert.equal(requests[0], '');
		assert.equal(await list.locator('.candidate-row').count(), 5);
		assert.equal(await list.locator('.role-teacher').count(), 3);
		assert.equal(await list.locator('.role-kholleur').count(), 2);
		assert.equal(
			await dialog.getByRole('button', { name: 'Rechercher', exact: true }).count(),
			0
		);
		const query = dialog.getByLabel('Ajouter un enseignant ou un khôlleur', { exact: true });
		await query.fill('A');
		await list.locator('.candidate-row').nth(4).waitFor();
		assert.ok(requests.includes('A'));
		await query.fill('zz');
		await list
			.getByText('Aucun enseignant éligible ou khôlleur actif trouvé.', { exact: true })
			.waitFor();
		await query.fill('');
		await list.locator('.candidate-row').nth(4).waitFor();
		await list.getByRole('button', { name: 'Ajouter Alex Martin 1', exact: true }).click();
		await list.getByRole('button', { name: 'Ajouter Alex Martin 6', exact: true }).waitFor();
		assert.equal(
			await list.getByRole('button', { name: 'Ajouter Alex Martin 1', exact: true }).count(),
			0
		);
		assert.equal(await list.locator('.candidate-row').count(), 5);
		await page.keyboard.press('Escape');
		await dialog.waitFor({ state: 'hidden' });
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('visual pickers render icons, bind numeric/string choices and support keyboard navigation', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.goto(`${server.resolvedUrls.local[0]}__picker`);
		const icons = page.getByRole('group', { name: 'Icône', exact: true });
		await icons
			.getByRole('radio', { name: 'Livre', exact: true })
			.waitFor({ state: 'attached', timeout: 10000 })
			.catch(() => {
				assert.fail(`Picker did not render: ${errors.join('; ')}`);
			});
		assert.equal(await icons.getByRole('radio').count(), lessonIcons.length);
		const paths = await icons
			.locator('svg')
			.evaluateAll((elements) =>
				elements
					.filter((element) => element.getAttribute('width') === '22')
					.map((element) => element.querySelector('path').getAttribute('d'))
			);
		assert.equal(new Set(paths).size, lessonIcons.length);
		await icons.getByText('Physique', { exact: true }).click();
		assert.equal(await page.getByLabel('Icône choisie').textContent(), 'physics');
		assert.equal(
			await icons.getByRole('radio', { name: 'Physique', exact: true }).isChecked(),
			true
		);
		await page.keyboard.press('ArrowRight');
		assert.equal(await page.getByLabel('Icône choisie').textContent(), 'biology');
		const subjects = page.getByRole('group', { name: 'Matière', exact: true });
		assert.equal(await page.locator('form').evaluate((form) => form.checkValidity()), false);
		await subjects.getByText('Philosophie', { exact: true }).click();
		assert.equal(await page.getByLabel('Matière choisie').textContent(), '2');
		assert.equal(await page.locator('form').evaluate((form) => form.checkValidity()), true);
		await page.keyboard.press('ArrowLeft');
		assert.equal(await page.getByLabel('Matière choisie').textContent(), '1');
		assert.equal(
			await subjects
				.locator('.choice-icon')
				.first()
				.evaluate((element) => getComputedStyle(element).backgroundColor),
			'rgb(18, 52, 86)'
		);
		await page.getByRole('button', { name: 'Désactiver les matières' }).click();
		assert.equal(await subjects.getByRole('radio').first().isDisabled(), true);
		assert.equal(
			await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
			true
		);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});
