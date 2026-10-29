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
						return 'export const beforeNavigate = () => {}; export const goto = async () => {}; export const invalidateAll = async () => {};';
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
						const fixture = _request.url.includes('directory')
							? 'DirectoryHarness'
							: _request.url.includes('groups')
								? 'GroupsHarness'
								: _request.url.includes('error')
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

test('staff profiles hide school sections in account and dashboard views', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage();
		for (const role of ['user', 'teacher', 'kholleur', 'admin']) {
			await page.goto(
				`${server.resolvedUrls.local[0]}__picker?directory&schoolView&memberRole=${role}`
			);
			await page
				.getByRole('heading', { name: 'Informations personnelles', exact: true })
				.waitFor();
			for (const name of ['Parcours scolaire', 'Projet d’orientation']) {
				assert.equal(
					await page.getByRole('heading', { name, exact: true }).count(),
					role === 'user' ? 2 : 0
				);
			}
			assert.equal(
				await page.getByRole('heading', { name: /Adulte référent/ }).count(),
				role === 'user' ? 2 : 0
			);
			await page.getByRole('heading', { name: 'Les repères de votre compte' }).waitFor();
			assert.equal(await page.getByText('Mot de passe modifié', { exact: true }).count(), 0);
		}
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('attendance PDF opens from below the promotion roster with the selected identifier', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		for (const role of ['admin', 'teacher', 'kholleur']) {
			const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
			await page.route('**/dashboard/data?**', (route) => {
				const resource = new URL(route.request().url()).searchParams.get('resource');
				return route.fulfill({
					json:
						resource === 'promotionGroups'
							? { students: [], partitions: [] }
							: resource === 'promotions'
								? {
										items: [
											{
												id: 1,
												identifier: 'PT',
												year: 2026,
												color: '#244BC1',
												is_active: true
											}
										],
										total: 1,
										offset: 0,
										limit: 12
									}
								: { items: [], total: 0, offset: 0, limit: 50 }
				});
			});
			await page.goto(
				`${server.resolvedUrls.local[0]}__picker?directory&promotionView${role === 'admin' ? '' : '&teacher'}${role === 'kholleur' ? '&kholleur' : ''}`
			);
			await page.getByRole('heading', { name: 'PT', exact: true }).waitFor();
			const link = page.getByRole('link', { name: 'Ouvrir le PDF', exact: true });
			if (role === 'kholleur') {
				assert.equal(await link.count(), 0);
			} else {
				await link.waitFor();
				assert.equal(
					await link.getAttribute('href'),
					'/dashboard/attendance?promotionId=1'
				);
				assert.equal(await link.getAttribute('target'), '_blank');
				const section = page.getByRole('region', {
					name: 'Feuille de présence',
					exact: true
				});
				assert.equal(
					await section.evaluate(
						(element) =>
							element.previousElementSibling?.querySelector('.eyebrow')
								?.textContent === 'Membres de la promotion'
					),
					true
				);
				await page
					.context()
					.route('**/dashboard/attendance?**', (route) =>
						route.fulfill({ contentType: 'text/plain', body: 'Synthetic PDF endpoint' })
					);
				const opened = page.waitForEvent('popup');
				await link.click();
				const popup = await opened;
				await popup.waitForLoadState();
				assert.match(popup.url(), /\/dashboard\/attendance\?promotionId=1$/);
				await popup.close();
			}
			await page.close();
		}
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('saved group tags appear in promotion rosters, popup cards and full profiles', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		for (const [teacher, archived] of [
			[false, false],
			[true, false],
			[false, true]
		]) {
			const page = await browser.newPage({
				viewport: { width: teacher ? 390 : 1280, height: 1000 }
			});
			const errors = [];
			page.on('pageerror', (error) => errors.push(error.message));
			const promotions = [
				{ id: 1, identifier: 'PT', year: 2026, color: '#244BC1', is_active: true },
				{ id: 2, identifier: 'PTSI', year: 2026, color: '#67449A', is_active: true }
			].filter((promotion) => !teacher || promotion.id === 1);
			const group_assignments = [
				{ promotion_id: 1, kind: 'halves', number: 1 },
				{ promotion_id: 1, kind: 'thirds', number: 3 },
				{ promotion_id: 1, kind: 'kholles', number: 2 },
				...(!teacher ? [{ promotion_id: 2, kind: 'kholles', number: 7 }] : [])
			];
			const student = {
				id: 3,
				username: 'alice123',
				first_name: 'Alice',
				last_name: 'Martin',
				email: 'martin.alice@test.fr',
				roles: ['user'],
				status: archived ? 'disabled' : 'active',
				created_at: '2026-01-01T00:00:00Z',
				promotions,
				group_assignments,
				last_login_at: null,
				password_changed_at: null,
				login_count: 0,
				invitation: { status: 'none' }
			};
			await page.route('**/dashboard/data?**', (route) => {
				const resource = new URL(route.request().url()).searchParams.get('resource');
				let json;
				if (resource === 'user') json = student;
				else if (resource === 'subjects') json = { items: [], total: 0 };
				else if (resource === 'search') json = [student];
				else if (resource === 'users')
					json = {
						items: [
							student,
							{ ...student, id: 4, first_name: 'Benoît', group_assignments: [] }
						],
						total: 2
					};
				else json = { items: promotions, total: promotions.length };
				return route.fulfill({ json });
			});
			await page.goto(
				`${server.resolvedUrls.local[0]}__picker?directory${teacher ? '&teacher' : ''}${archived ? '&archived' : ''}`
			);
			const row = page.locator('.account-row').filter({ hasText: 'Alice Martin' });
			await row.waitFor();
			assert.equal(
				await row.evaluate((element) => element.classList.contains('archived-account')),
				archived
			);
			assert.deepEqual(await row.locator('.group-tags .tag').allTextContents(), [
				'A',
				'Z',
				'02'
			]);
			assert.equal(await row.getByLabel('Demi-groupe A', { exact: true }).count(), 1);
			assert.equal(await row.getByLabel('Tiers de groupe Z', { exact: true }).count(), 1);
			assert.equal(await row.getByLabel('Groupe de khôlle 02', { exact: true }).count(), 1);
			assert.equal(
				await page
					.locator('.account-row')
					.filter({ hasText: 'Benoît Martin' })
					.locator('.group-tags')
					.count(),
				0
			);
			const full = page.getByRole('region', { name: 'Promotions et groupes', exact: true });
			assert.deepEqual(
				await full
					.locator('.membership-row')
					.first()
					.locator('.group-tags .tag')
					.allTextContents(),
				['A', 'Z', '02']
			);
			assert.equal(await full.locator('.membership-row').count(), teacher ? 1 : 2);
			const search = page.getByRole('textbox', { name: 'Rechercher un compte', exact: true });
			await search.fill('Alice');
			await page.waitForResponse((response) => response.url().includes('resource=search'));
			await row.waitFor();
			assert.deepEqual(await row.locator('.group-tags .tag').allTextContents(), [
				'A',
				'Z',
				'02'
			]);
			await row.click();
			const dialog = page.getByRole('dialog');
			await dialog.locator('.membership-row').first().waitFor();
			assert.equal(
				await dialog
					.locator('.profile-hero')
					.evaluate((element) => element.classList.contains('archived-account')),
				archived
			);
			assert.equal(await dialog.locator('.membership-row').count(), teacher ? 1 : 2);
			assert.deepEqual(
				await dialog
					.locator('.membership-row')
					.first()
					.locator('.group-tags .tag')
					.allTextContents(),
				['A', 'Z', '02']
			);
			assert.equal(
				await dialog
					.getByRole('link', { name: 'Voir la fiche complète' })
					.getAttribute('href'),
				'/dashboard/user?id=3'
			);
			if (teacher)
				assert.equal(
					await dialog.getByLabel('Groupe de khôlle 07', { exact: true }).count(),
					0
				);
			assert.equal(
				await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
				true
			);
			assert.deepEqual(errors, []);
			await page.close();
		}
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('archived pupils stay grey and movable outside effective khôlle sizes', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		const students = ['Alice', 'Benoît', 'Camille', 'Diane', 'Émile', 'Farah'].map(
			(name, index) => ({
				id: index + 1,
				first_name: name,
				last_name: 'Martin',
				status: index === 5 ? 'disabled' : 'active'
			})
		);
		let partition = {
			kind: 'kholles',
			revision: 'a'.repeat(32),
			target_size: 3,
			groups: [
				{ number: 1, x: 20, y: 20, student_ids: [1, 2, 3] },
				{ number: 2, x: 320, y: 20, student_ids: [4, 5] },
				{ number: 15, x: 620, y: 20, student_ids: [6] }
			]
		};
		const writes = [];
		await page.route('**/dashboard/data?**', (route) =>
			route.fulfill({ json: { students, partitions: [partition] } })
		);
		await page.route('**/dashboard/command', async (route) => {
			const input = route.request().postDataJSON();
			writes.push(input);
			partition = { ...partition, revision: 'b'.repeat(32), groups: input.data.groups };
			await route.fulfill({ json: partition });
		});
		await page.goto(`${server.resolvedUrls.local[0]}__picker?groups`);
		await page.getByRole('button', { name: 'Groupes de khôlle', exact: true }).click();
		const archivedGroup = page.getByRole('region', { name: 'Groupe 15', exact: true });
		await archivedGroup.waitFor();
		assert.equal(await archivedGroup.locator('.bubble-handle .tag').textContent(), '0');
		const archivedStudent = page.getByRole('button', {
			name: 'Farah Martin · Archivé',
			exact: true
		});
		assert.equal(
			await archivedStudent
				.locator('.student-name')
				.evaluate((element) => getComputedStyle(element).textDecorationLine),
			'line-through'
		);
		assert.equal(
			await archivedStudent.evaluate((element) => getComputedStyle(element).filter),
			'grayscale(1)'
		);
		await page.getByRole('button', { name: 'Modifier les groupes', exact: true }).click();
		assert.equal(await archivedStudent.isEnabled(), true);
		assert.equal(await archivedStudent.getAttribute('draggable'), 'true');
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).isEnabled(),
			true
		);
		const secondGroup = page.getByRole('region', { name: 'Groupe 02', exact: true });
		await archivedStudent.dragTo(
			secondGroup.getByRole('button', { name: 'Déplacer ici', exact: true })
		);
		assert.equal(await secondGroup.locator('.student-chip').count(), 3);
		assert.equal(await secondGroup.locator('.bubble-handle .tag').textContent(), '2');
		await archivedGroup
			.getByRole('button', { name: 'Retirer ce groupe vide', exact: true })
			.click();
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await page.getByText('Répartition enregistrée.', { exact: true }).waitFor();
		assert.deepEqual(writes[0].data.archived_ids, [6]);
		assert.ok(
			writes[0].data.groups.find((group) => group.number === 2).student_ids.includes(6)
		);
		assert.equal(
			writes[0].data.groups.some((group) => group.number === 15),
			false
		);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('newcomers join existing groups in both views and khôlles can be paired and split', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		const students = ['Alice', 'Benoît', 'Camille', 'Diane'].map((name, index) => ({
			id: index + 1,
			first_name: name,
			last_name: 'Martin',
			status: 'active'
		}));
		const partition = {
			kind: 'kholles',
			revision: 'a'.repeat(32),
			target_size: 2,
			groups: [
				{ number: 1, x: 20, y: 20, student_ids: [1, 2] },
				{ number: 2, x: 320, y: 20, student_ids: [3] }
			]
		};
		const writes = [];
		await page.route('**/dashboard/data?**', (route) =>
			route.fulfill({ json: { students, partitions: [partition] } })
		);
		await page.route('**/dashboard/command', async (route) => {
			const input = route.request().postDataJSON();
			writes.push(input);
			await route.fulfill({ json: { ...partition, groups: input.data.groups } });
		});
		await page.goto(`${server.resolvedUrls.local[0]}__picker?groups`);
		await page.getByRole('button', { name: 'Groupes de khôlle', exact: true }).click();
		const bubble = (name) => page.getByRole('region', { name, exact: true });
		const pupil = (name) => page.getByRole('button', { name: `${name} Martin`, exact: true });
		const save = page.getByRole('button', { name: 'Enregistrer', exact: true });
		await page.getByRole('button', { name: 'Affecter ces élèves', exact: true }).click();
		assert.equal(await save.isDisabled(), true);
		await pupil('Diane').dragTo(bubble('Groupe 02').locator('.bubble-members'));
		assert.equal(await save.isEnabled(), true);
		assert.equal(await bubble('Groupe 01').locator('.student-chip').count(), 2);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		await page.getByRole('button', { name: 'Vue liste', exact: true }).click();
		await page.getByRole('button', { name: 'Affecter ces élèves', exact: true }).click();
		await pupil('Diane').focus();
		await page.keyboard.press('Enter');
		await bubble('Groupe 02')
			.getByRole('button', { name: 'Déplacer ici', exact: true })
			.click();
		assert.equal(await save.isEnabled(), true);
		await save.click();
		await page.getByText('Répartition enregistrée.', { exact: true }).waitFor();
		assert.deepEqual(
			writes[0].data.groups.map((group) => group.student_ids),
			[
				[1, 2],
				[3, 4]
			]
		);
		assert.equal(writes.length, 1);
		await page.getByRole('button', { name: 'Vue bulles', exact: true }).click();
		await page.getByRole('button', { name: 'Modifier les groupes', exact: true }).click();
		await pupil('Alice').dragTo(pupil('Camille'));
		assert.equal(await bubble('Groupe 03').locator('.student-chip').count(), 2);
		assert.equal(
			await bubble('Groupe 01').locator('.student-chip').textContent(),
			'Benoît Martin'
		);
		assert.equal(
			await bubble('Groupe 02').locator('.student-chip').textContent(),
			'Diane Martin'
		);
		assert.equal(await save.isDisabled(), true);
		await pupil('Alice').dragTo(page.locator('.group-board'), {
			targetPosition: { x: 650, y: 320 }
		});
		assert.equal(await page.locator('.group-bubble').count(), 4);
		assert.equal(
			await bubble('Groupe 03').locator('.student-chip').textContent(),
			'Camille Martin'
		);
		assert.equal(
			await bubble('Groupe 04').locator('.student-chip').textContent(),
			'Alice Martin'
		);
		assert.equal(await save.isDisabled(), true);
		await pupil('Alice').click();
		await bubble('Groupe 03')
			.getByRole('button', { name: 'Déplacer ici', exact: true })
			.click();
		await bubble('Groupe 04')
			.getByRole('button', { name: 'Retirer ce groupe vide', exact: true })
			.click();
		await pupil('Diane').click();
		await bubble('Groupe 01')
			.getByRole('button', { name: 'Déplacer ici', exact: true })
			.click();
		await bubble('Groupe 02')
			.getByRole('button', { name: 'Retirer ce groupe vide', exact: true })
			.click();
		assert.equal(await save.isEnabled(), true);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(await page.locator('.group-bubble').count(), 2);
		assert.equal(writes.length, 1);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('custom group editing preserves archived pupils and lets them be removed and added', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
		const students = [
			{ id: 1, first_name: 'Alice', last_name: 'Martin', status: 'active' },
			{ id: 2, first_name: 'Farah', last_name: 'Martin', status: 'disabled' }
		];
		let groups = [
			{
				id: 12,
				name: 'Allemand',
				revision: 'a'.repeat(32),
				student_ids: [1, 2],
				x: 320,
				y: 20
			}
		];
		const writes = [];
		await page.route('**/dashboard/data?**', (route) =>
			route.fulfill({
				json: route.request().url().includes('customPromotionGroups')
					? { groups, live: false }
					: { students, partitions: [] }
			})
		);
		await page.route('**/dashboard/command', async (route) => {
			const input = route.request().postDataJSON();
			writes.push(input);
			groups = [{ ...groups[0], ...input.data }];
			await route.fulfill({ json: groups[0] });
		});
		await page.goto(`${server.resolvedUrls.local[0]}__picker?groups`);
		await page.getByRole('button', { name: 'Groupes personnalisés', exact: true }).click();
		const custom = page.getByRole('region', { name: 'Allemand', exact: true });
		const source = page.getByRole('region', { name: 'Classe entière', exact: true });
		const archived = (region) =>
			region.getByRole('button', { name: 'Farah Martin · Archivé', exact: true });
		await custom.getByRole('button', { name: 'Modifier', exact: true }).click();
		assert.equal(await archived(custom).isEnabled(), true);
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await custom.getByRole('button', { name: 'Modifier', exact: true }).waitFor();
		assert.deepEqual(writes[0].data.student_ids, [1, 2]);
		await custom.getByRole('button', { name: 'Modifier', exact: true }).click();
		await archived(custom).dragTo(source.locator('.bubble-members'));
		assert.equal(await custom.locator('.student-chip').count(), 1);
		await archived(source).click();
		await custom.getByRole('button', { name: 'Ajouter ici', exact: true }).click();
		assert.equal(await custom.locator('.student-chip').count(), 2);
		await page.getByRole('button', { name: 'Vue liste', exact: true }).click();
		await archived(custom).dragTo(source.locator('.bubble-members'));
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await custom.getByRole('button', { name: 'Modifier', exact: true }).waitFor();
		assert.deepEqual(writes[1].data.student_ids, [1]);
	} finally {
		await browser?.close();
		await server.close();
	}
});

test('promotion groups support bubble movement, transfers, saved drafts and independent deletion', async () => {
	const server = await pickerServer();
	let browser;
	try {
		await server.listen();
		browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
		const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
		const errors = [];
		page.on('pageerror', (error) => errors.push(error.message));
		const students = ['Alice', 'Benoît', 'Camille', 'Diane', 'Émile', 'Farah'].map(
			(name, index) => ({ id: index + 1, first_name: name, last_name: 'Martin' })
		);
		const initial = [
			{ number: 1, x: 20, y: 20, student_ids: [1, 2, 3] },
			{ number: 2, x: 320, y: 20, student_ids: [4, 5, 6] }
		];
		let partitions = ['halves', 'kholles'].map((kind) => ({
			kind,
			revision: 'a'.repeat(32),
			target_size: 3,
			groups: structuredClone(initial)
		}));
		const commands = [];
		await page.route('**/dashboard/data?**', (route) =>
			route.fulfill({ json: { students, partitions } })
		);
		await page.route('**/dashboard/command', async (route) => {
			const input = route.request().postDataJSON();
			commands.push(input);
			if (input.command === 'previewGroups') {
				const count =
					input.kind === 'kholles'
						? Math.ceil(students.length / input.data.target_size)
						: input.kind === 'thirds'
							? 3
							: 2;
				await route.fulfill({
					json: Array.from({ length: count }, (_, index) => ({
						number: index + 1,
						x: index * 300 + 20,
						y: 20,
						student_ids: (input.kind === 'kholles'
							? students.slice(
									index * input.data.target_size,
									(index + 1) * input.data.target_size
								)
							: students.filter((_, i) => i % count === index)
						).map((student) => student.id)
					}))
				});
			} else if (input.command === 'saveGroups') {
				const partition = {
					kind: input.kind,
					revision: 'b'.repeat(32),
					target_size: input.data.target_size,
					groups: input.data.groups
				};
				partitions = [...partitions.filter((item) => item.kind !== input.kind), partition];
				await route.fulfill({ json: partition });
			} else {
				partitions = partitions.filter((item) => item.kind !== input.kind);
				await route.fulfill({ json: { success: true } });
			}
		});
		const url = `${server.resolvedUrls.local[0]}__picker?groups`;
		await page.goto(url);
		const bubbles = page.locator('.group-bubble');
		await bubbles.first().waitFor();
		await page.getByRole('button', { name: 'Modifier les groupes', exact: true }).click();
		await bubbles.first().waitFor();
		const editActions = page.getByRole('group', {
			name: 'Actions d’édition des groupes',
			exact: true
		});
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).count(),
			1
		);
		assert.equal(
			await editActions.evaluate((element) =>
				Boolean(
					element.compareDocumentPosition(document.querySelector('.group-board')) &
					Node.DOCUMENT_POSITION_FOLLOWING
				)
			),
			true
		);
		await page.setViewportSize({ width: 1280, height: 600 });
		const actionsTop = await editActions.evaluate(
			(element) => element.getBoundingClientRect().top + scrollY
		);
		await page.evaluate((top) => window.scrollTo(0, top + 80), actionsTop);
		assert.ok((await editActions.boundingBox()).y <= 13);
		await page.evaluate(() => window.scrollTo(0, 0));
		await page.setViewportSize({ width: 1280, height: 1000 });
		await bubbles
			.first()
			.getByRole('button', { name: 'Alice Martin', exact: true })
			.dragTo(bubbles.nth(1).locator('.bubble-members'));
		assert.equal(await bubbles.nth(1).locator('.student-chip').count(), 4);
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).isDisabled(),
			true
		);
		await bubbles.nth(1).getByRole('button', { name: 'Diane Martin', exact: true }).click();
		await bubbles.first().getByRole('button', { name: 'Déplacer ici', exact: true }).click();
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).isEnabled(),
			true
		);
		const handle = bubbles.first().locator('.bubble-handle');
		const box = await handle.boundingBox();
		await page.mouse.move(box.x + 50, box.y + 20);
		await page.mouse.down();
		await page.mouse.move(box.x + 100, box.y + 60, { steps: 5 });
		await page.mouse.up();
		await handle.focus();
		await page.keyboard.press('ArrowRight');
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await page.getByText('Répartition enregistrée.', { exact: true }).waitFor();
		const saved = commands.find((input) => input.command === 'saveGroups');
		assert.equal(saved.data.groups[0].x, 90);
		assert.equal(saved.data.groups[0].y, 60);
		assert.deepEqual(saved.data.groups[0].student_ids, [2, 3, 4]);
		await page.getByRole('button', { name: 'Tiers de groupe', exact: true }).click();
		await page.getByRole('button', { name: 'Générer', exact: true }).click();
		await page.getByText('Mode édition · modifications non enregistrées.').waitFor();
		assert.equal(await bubbles.count(), 3);
		assert.equal(
			partitions.some((partition) => partition.kind === 'thirds'),
			false
		);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(await bubbles.count(), 0);
		await page.getByRole('button', { name: 'Groupes de khôlle', exact: true }).click();
		await page.getByRole('button', { name: 'Modifier les groupes', exact: true }).click();
		await bubbles.nth(1).getByRole('button', { name: 'Diane Martin', exact: true }).click();
		await bubbles.first().getByRole('button', { name: 'Déplacer ici', exact: true }).click();
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).isDisabled(),
			true
		);
		await bubbles.nth(1).getByRole('button', { name: 'Émile Martin', exact: true }).click();
		await bubbles.first().getByRole('button', { name: 'Déplacer ici', exact: true }).click();
		assert.equal(await bubbles.first().locator('.student-chip').count(), 5);
		assert.equal(await bubbles.nth(1).locator('.student-chip').count(), 1);
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).isDisabled(),
			true
		);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		const target = page.getByLabel('Taille cible à la génération', { exact: true });
		assert.equal(await target.inputValue(), '3');
		assert.deepEqual(
			await target
				.locator('option')
				.evaluateAll((options) => options.map((option) => option.value)),
			['2', '3', '4', '5']
		);
		await target.selectOption('5');
		await page.getByRole('button', { name: 'Régénérer', exact: true }).click();
		await page.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await page.getByText('Mode édition · modifications non enregistrées.').waitFor();
		assert.equal(commands.at(-1).data.target_size, 5);
		assert.equal(await bubbles.first().locator('.student-chip').count(), 5);
		assert.equal(await bubbles.nth(1).locator('.student-chip').count(), 1);
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer', exact: true }).isEnabled(),
			true
		);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		await page.getByRole('button', { name: 'Supprimer la répartition', exact: true }).click();
		assert.equal(
			commands.some((input) => input.command === 'deleteGroups'),
			false
		);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(await bubbles.count(), 2);
		await page.getByRole('button', { name: 'Supprimer la répartition', exact: true }).click();
		await page.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await page.getByText('Répartition supprimée.', { exact: true }).waitFor();
		assert.deepEqual(
			partitions.map((partition) => partition.kind),
			['halves']
		);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(url + '&readonly');
		await bubbles.first().waitFor();
		assert.equal(
			await page.getByRole('button', { name: 'Modifier les groupes', exact: true }).count(),
			0
		);
		assert.equal(
			await page
				.getByRole('button', { name: 'Supprimer la répartition', exact: true })
				.count(),
			0
		);
		const before = commands.length;
		await bubbles.first().locator('.bubble-handle').focus();
		await page.keyboard.press('ArrowRight');
		await page.getByRole('button', { name: 'Vue liste', exact: true }).click();
		assert.equal(
			await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
			true
		);
		assert.equal(commands.length, before);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		await server.close();
	}
});

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
