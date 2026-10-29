/** Exercise the built Svelte UI; actual data integrity and authorization have PostgreSQL tests. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { chromium } from 'playwright';

test('live annual management, recurrence confirmations, hours, archival and annual staff availability', async () => {
	const revision = 'a'.repeat(32),
		mutations = [],
		previews = [],
		errors = [];
	let role = 'admin';
	let pupilHasPromotion = true;
	let releaseMonitoring;
	let subscriptionToken = 'a'.repeat(86),
		subscriptionRevoked = false;
	const subscriptionCommands = [];
	const settings = {
		start: '2026-09-01',
		end: '2027-06-30',
		day_start: 28800,
		day_end: 68400,
		session_minutes: 60,
		saturday: false,
		breaks: [],
		lunch_start: 43200,
		lunch_end: 50400,
		holidays: []
	};
	const slots = Array.from({ length: 22 }, (_, index) => [
		28800 + index * 1800,
		30600 + index * 1800
	]);
	const source = {
		id: revision,
		lineage: revision,
		starts_on: '2026-09-07',
		start_slot: 0,
		duration_slots: 2,
		subject_id: 1,
		teacher_id: 2,
		room_id: 1,
		kind: 'course',
		title: 'Maths',
		interval: 1,
		until: null,
		target_kind: 'promotion',
		target_number: null,
		target_user_id: null,
		exceptions: {}
	};
	const agenda = {
		id: 1,
		name: 'PTSI annuel',
		promotion_id: 1,
		revision,
		is_paused: false,
		is_archived: false,
		years: [{ id: 1, school_year: 2026, revision }]
	};
	const teachers = [
		{ id: 2, name: 'Mme Test', subject_ids: [1], roles: ['teacher', 'kholleur'] },
		{ id: 4, name: 'M. Partagé', subject_ids: [], roles: ['teacher'] }
	];
	const subjects = [
			{ id: 1, name: 'Mathématiques', color: '#244BC1' },
			{ id: 2, name: 'Allemand', color: '#2E8B57' },
			{ id: 3, name: 'Sciences industrielles de l’ingénieur', color: '#A34E18' }
		],
		rooms = [{ id: 1, name: 'B402', revision }];
	const tags = [
		{ school_year: 2027, revision, used: false },
		{ school_year: 2026, revision, used: true }
	];
	const customGroups = [];
	const promotion = {
		id: 1,
		identifier: 'PTSI',
		year: 2026,
		color: '#244BC1',
		is_active: true,
		student_count: 1
	};
	let autoArchive = true;
	let pattern = null;
	const kholleHours = new Map();
	function board(preview = false) {
		return {
			calendars: [agenda],
			years: [
				{
					id: 1,
					calendar_id: 1,
					school_year: 2026,
					settings,
					revision,
					slots,
					weeks: { '2026-09-07': 1, '2026-09-14': 2 },
					series: [source],
					hours: [
						{
							subject_id: 1,
							course: 15.78,
							td: 0,
							tp: 0,
							kholle: 0,
							total: 15.78,
							weekly: { course: 7.89, td: 0, tp: 0, kholle: 0, total: 7.89 }
						},
						{
							subject_id: 2,
							course: 4,
							td: 0,
							tp: 0,
							kholle: 0,
							total: 4,
							weekly: { course: 2, td: 0, tp: 0, kholle: 0, total: 2 }
						},
						{
							subject_id: 3,
							course: 1,
							td: 0,
							tp: 0,
							kholle: 0,
							total: 1,
							weekly: { course: 0.5, td: 0, tp: 0, kholle: 0, total: 0.5 }
						}
					]
				}
			],
			events: [
				{
					...source,
					id: 'event-1',
					series_id: revision,
					source_date: '2026-09-07',
					start: '2026-09-07T08:00:00+02:00',
					end: '2026-09-07T09:00:00+02:00',
					calendar_id: 1,
					promotion_id: 1,
					year_id: 1,
					school_year: 2026,
					color: '#244BC1',
					teacher: 'Mme Test',
					teacher_roles: ['teacher', 'kholleur'],
					teacher_available: true,
					room: 'B402'
				}
			],
			members: [
				{ id: 3, name: 'Élève Test', roles: ['user'], promotion_ids: [1], assignments: [] }
			],
			groups: customGroups.map((group) => ({
				promotion_id: 1,
				kind: 'custom',
				number: group.id,
				name: group.name,
				student_ids: group.student_ids
			})),
			warnings: [],
			issues: preview
				? [
						{
							code: 'lunch-2026-09-07',
							severity: 'critical',
							message: 'Repas : 1 élève sans une séance complète pour manger.'
						}
					]
				: [],
			availability: [{ teacher_id: 2, school_year: 2026, ranges: [] }],
			teacher_commitments: []
		};
	}
	const backend = createServer(async (request, response) => {
		const url = new URL(request.url, 'http://localhost');
		response.setHeader('Content-Type', 'application/json');
		const reply = (value) => response.end(JSON.stringify(value));
		if (url.pathname === '/api/v1/admin/monitoring') {
			if (url.searchParams.has('interval')) return reply({ statuses: { 200: 9, 503: 1 } });
			await new Promise((resolve) => {
				releaseMonitoring = resolve;
			});
			return reply({
				requests: 10,
				mean_ms: 12,
				p95_ms: 25,
				server_error_rate: 10,
				dropped_measurements: 0,
				points: [
					{
						timestamp: '2026-10-29T10:00:00Z',
						requests: 10,
						mean_ms: 12,
						p95_ms: 25,
						max_ms: 30,
						successes: 9,
						redirects: 0,
						client_errors: 0,
						server_errors: 1,
						incomplete: 0,
						ics_refused: 0
					}
				],
				categories: [
					{
						key: 'other',
						label: 'Autres',
						requests: 10,
						mean_ms: 12,
						p95_ms: 25,
						max_ms: 30,
						server_errors: 1
					}
				]
			});
		}
		if (url.pathname === '/api/v1/auth/me/profile') return reply(null);
		if (url.pathname === '/api/v1/auth/me/promotions') return reply([]);
		if (url.pathname === '/api/v1/timetable/subscription')
			return reply({
				token: role === 'pupil' && !pupilHasPromotion ? null : subscriptionToken,
				revoked: subscriptionRevoked
			});
		if (url.pathname.startsWith('/api/v1/timetable/feed/')) {
			assert.equal(request.headers.cookie, undefined);
			response.setHeader('Content-Type', 'text/calendar');
			return response.end(
				'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//FR\r\nEND:VCALENDAR\r\n'
			);
		}
		if (url.pathname === '/api/v1/timetable/subscriptions/bulk') {
			let raw = '';
			for await (const chunk of request) raw += chunk;
			const data = JSON.parse(raw);
			subscriptionCommands.push(data);
			subscriptionRevoked = data.action === 'revoke';
			if (!subscriptionRevoked) subscriptionToken = 'b'.repeat(86);
			return reply({ affected: 2 });
		}
		if (url.pathname === '/api/v1/admin/statistics')
			return reply({
				scope: 'admin',
				period: 'week',
				timestamps: [],
				generated_at: new Date().toISOString(),
				series: {},
				totals: {
					unique_logins: 0,
					logins: 0,
					failures: 0,
					limited: 0,
					attempts: 0,
					downloads: 0,
					downloaders: 0
				},
				storage: {
					files: 0,
					bytes: 0,
					quota_bytes: 0,
					reserved_bytes: 0,
					physical_bytes: 0,
					temporary_bytes: 0,
					pending_deletions: 0,
					formats: []
				},
				accounts: [],
				roles: [],
				promotions: [],
				promotion_staff: [],
				subjects: [],
				popular: [],
				courses: [],
				calendar_recent_users: 1,
				calendar_subscriptions: [
					{ label: 'Consulté', value: 1 },
					{ label: 'Jamais consulté', value: 1 }
				]
			});
		if (request.method === 'GET') {
			if (url.pathname === '/api/v1/promotion-groups/promotions/1') return reply(promotion);
			if (url.pathname === '/api/v1/admin/promotions')
				return reply({ items: [promotion], total: 1, offset: 0, limit: 12 });
			if (url.pathname === '/api/v1/admin/users')
				return reply({ items: [], total: 0, offset: 0, limit: 50 });
			if (url.pathname === '/api/v1/promotion-groups/1')
				return reply({
					students: [{ id: 3, first_name: 'Élève', last_name: 'Test', status: 'active' }],
					partitions: [
						{
							kind: 'halves',
							revision,
							target_size: 3,
							groups: [
								{ number: 1, x: 20, y: 20, student_ids: [3] },
								{ number: 2, x: 320, y: 20, student_ids: [] }
							]
						}
					]
				});
			if (url.pathname === '/api/v1/promotion-groups/1/custom/groups')
				return reply({ groups: customGroups, live: true });
		}
		if (url.pathname === '/api/v1/site')
			return reply({
				settings: {
					name: 'Sophikron',
					home_text: '',
					text_color: '#244BC1',
					holiday_color: '#ffd166'
				},
				timelines: [],
				events: [],
				today: '2026-09-07'
			});
		if (url.pathname === '/api/v1/auth/me')
			return reply({
				id: 1,
				username: 'test',
				first_name: 'Camille',
				last_name: 'Test',
				is_bootstrap: false,
				status: 'active',
				roles: [role === 'pupil' ? 'user' : role],
				permissions:
					role === 'admin'
						? ['users.manage', 'users.read', 'promotions.manage', 'statistics.read']
						: role === 'teacher'
							? ['teaching.read', 'teacher.access']
							: ['user.access']
			});
		if (url.pathname === '/api/v1/timetable/catalog')
			return reply({
				administrator: role === 'admin',
				today: '2026-09-07',
				calendars: role === 'admin' || !agenda.is_archived ? [agenda] : [],
				common_years: tags,
				promotions: [{ id: 1, name: 'PTSI 2026' }],
				teachers,
				subjects,
				rooms
			});
		if (url.pathname === '/api/v1/timetable/configuration')
			return reply({
				years: tags,
				rooms,
				today: '2026-09-07',
				preferences: { auto_archive: autoArchive, revision }
			});
		if (url.pathname === '/api/v1/timetable/board') return reply(board());
		if (url.pathname === '/api/v1/timetable/staff/catalog')
			return reply({
				administrator: role === 'admin',
				today: '2026-09-07',
				teachers,
				subjects,
				years: tags.map((tag) => ({
					school_year: tag.school_year,
					settings: {
						...settings,
						start: tag.school_year + '-09-01',
						end: tag.school_year + 1 + '-08-31',
						saturday: true
					},
					slots
				}))
			});
		if (url.pathname === '/api/v1/timetable/staff/board')
			return reply({
				availability: [
					{
						teacher_id: 2,
						revision: pattern ? revision : null,
						default: pattern === null,
						...(kholleHours.get(url.searchParams.get('school_year')) ?? {
							kholle_min_hours: 0,
							kholle_max_hours: 0
						}),
						ranges:
							pattern ??
							Array.from({ length: 6 }, (_, weekday) => ({
								weekday,
								start: 28800,
								end: weekday === 5 ? 43200 : 68400
							}))
					}
				],
				events: [],
				occupied_ranges: []
			});
		if (request.method !== 'GET') {
			let text = '';
			for await (const chunk of request) text += chunk;
			const data = JSON.parse(text || '{}');
			if (url.pathname.endsWith('/preview')) {
				previews.push({ path: url.pathname, data });
				return reply(
					url.pathname.includes('/settings/') ? { hidden: 1, added: 0 } : board(true)
				);
			}
			mutations.push({ path: url.pathname, data });
			if (url.pathname === '/api/v1/timetable/preferences') autoArchive = data.auto_archive;
			if (url.pathname.startsWith('/api/v1/promotion-groups/1/custom/')) {
				const id = Number(url.pathname.split('/').at(-1)) || 10;
				const index = customGroups.findIndex((item) => item.id === id);
				if (request.method === 'DELETE') {
					customGroups.splice(index, 1);
					return reply({ id, revision });
				}
				const group = {
					id,
					name: data.name,
					student_ids: data.student_ids,
					x: data.x,
					y: data.y,
					revision
				};
				if (index < 0) customGroups.push(group);
				else customGroups[index] = group;
				return reply({ id, revision });
			}
			if (url.pathname.endsWith('/availability')) {
				if ('ranges' in data) pattern = data.ranges;
				if ('kholle_min_hours' in data)
					kholleHours.set(url.pathname.split('/')[5], {
						kholle_min_hours: data.kholle_min_hours,
						kholle_max_hours: data.kholle_max_hours
					});
			}
			if (url.pathname.endsWith('/archive')) {
				agenda.is_archived = true;
				agenda.is_paused = true;
			}
			if (url.pathname.endsWith('/restore')) {
				agenda.is_archived = false;
				agenda.is_paused = true;
				if (data.detach_promotion) agenda.promotion_id = null;
			}
			if (url.pathname === '/api/v1/timetable/calendars/1')
				Object.assign(agenda, {
					name: data.name,
					promotion_id: data.promotion_id,
					is_paused: data.is_paused
				});
			if (url.pathname.includes('/series/') && data.block) {
				source.title = data.block.title;
				source.teacher_ids = data.block.teacher_ids;
			}
			return reply({ id: 1, revision });
		}
		response.writeHead(404).end();
	});
	await new Promise((resolve) => backend.listen(0, '127.0.0.1', resolve));
	const child = spawn(
		process.execPath,
		[
			'--input-type=module',
			'-e',
			"import { createServer } from 'node:http'; let handler; const server=createServer((req,res)=>handler(req,res)); server.listen(0,'127.0.0.1',async()=>{process.env.ORIGIN='http://127.0.0.1:'+server.address().port;({handler}=await import('./build/handler.js'));console.log('PORT='+server.address().port);});"
		],
		{
			cwd: new URL('..', import.meta.url),
			windowsHide: true,
			stdio: ['ignore', 'pipe', 'pipe'],
			env: {
				...process.env,
				NODE_ENV: 'production',
				BACKEND_ORIGIN: 'http://127.0.0.1:' + backend.address().port
			}
		}
	);
	let output = '',
		browser;
	child.stderr.on('data', (chunk) => (output += chunk));
	try {
		const origin = await new Promise((resolve, reject) => {
			const timer = setTimeout(() => reject(new Error('Startup timeout: ' + output)), 15000);
			child.once('error', reject);
			child.stdout.on('data', (chunk) => {
				output += chunk;
				const port = output.match(/PORT=(\d+)/)?.[1];
				if (port) {
					clearTimeout(timer);
					resolve('http://127.0.0.1:' + port);
				}
			});
		});
		browser = await chromium.launch({
			channel: process.env.BFF_BROWSER_CHANNEL || 'msedge',
			headless: true
		});
		const context = await browser.newContext({
			viewport: { width: 1440, height: 1000 },
			locale: 'fr-FR'
		});
		await context.addCookies([
			{ name: 'sophikron_session_dev', value: 'synthetic-session', url: origin }
		]);
		const page = await context.newPage();
		page.on('pageerror', (error) => errors.push(error.message));
		await context.grantPermissions(['clipboard-read', 'clipboard-write']);
		await page.goto(origin + '/me');
		const personalUrl = `${origin}/calendar-feed/${subscriptionToken}.ics`;
		assert.equal(await page.getByLabel('Votre lien personnel').inputValue(), personalUrl);
		assert.ok(
			await page
				.locator('.calendar-subscription')
				.evaluate(
					(element) =>
						element.getBoundingClientRect().top -
							element.previousElementSibling.getBoundingClientRect().bottom >=
						20
				)
		);
		const refused = await context.request.post(origin + '/timetable/command', {
			headers: { Origin: 'http://foreign.invalid' },
			data: {}
		});
		assert.equal(refused.status(), 403);
		assert.equal((await refused.json()).message, 'Origine de la demande refusée.');
		await page.getByRole('button', { name: 'Copier le lien', exact: true }).click();
		await page.getByRole('status').filter({ hasText: 'Lien copié.' }).waitFor();
		assert.equal(await page.evaluate(() => navigator.clipboard.readText()), personalUrl);
		await page.evaluate(() =>
			Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
		);
		await page.getByRole('button', { name: 'Copier le lien', exact: true }).click();
		await page.getByRole('status').filter({ hasText: 'Lien copié.' }).waitFor();
		assert.equal(
			await page
				.getByLabel('Votre lien personnel')
				.evaluate((element) => element.selectionEnd - element.selectionStart),
			personalUrl.length
		);
		await page.evaluate(() => delete navigator.clipboard);
		await page.reload();
		assert.equal(await page.getByLabel('Votre lien personnel').inputValue(), personalUrl);
		const publicFeed = await context.request.get(personalUrl);
		assert.equal(publicFeed.status(), 200);
		assert.ok((await publicFeed.text()).includes('BEGIN:VCALENDAR'));
		await page.goto(origin + '/dashboard?tab=configuration');
		await page.getByRole('button', { name: 'Révoquer les abonnements', exact: true }).click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Annuler', exact: true })
			.click();
		assert.equal(subscriptionCommands.length, 0);
		await page.getByRole('button', { name: 'Révoquer les abonnements', exact: true }).click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Confirmer', exact: true })
			.click();
		await page.getByRole('status').filter({ hasText: '2 compte(s) traité(s).' }).waitFor();
		assert.deepEqual(subscriptionCommands[0], { action: 'revoke', category: 'user' });
		await page.goto(origin + '/me');
		await page
			.getByRole('status')
			.filter({ hasText: 'Votre abonnement a été révoqué' })
			.waitFor();
		await page.goto(origin + '/dashboard?tab=configuration');
		await page.getByRole('button', { name: 'Générer de nouveaux liens', exact: true }).click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Confirmer', exact: true })
			.click();
		await page.getByRole('status').filter({ hasText: '2 compte(s) traité(s).' }).waitFor();
		await page.goto(origin + '/me');
		assert.equal(
			await page.getByLabel('Votre lien personnel').inputValue(),
			`${origin}/calendar-feed/${'b'.repeat(86)}.ics`
		);
		await page.goto(origin + '/dashboard?tab=statistics');
		await page.getByRole('status').filter({ hasText: 'Chargement du monitoring' }).waitFor();
		await page.getByRole('button', { name: 'Voir l’utilisation', exact: true }).waitFor();
		assert.ok(releaseMonitoring);
		releaseMonitoring();
		await page.getByRole('checkbox', { name: 'Afficher en pourcentage' }).waitFor();
		const monitor = page.locator('.api-monitoring');
		assert.equal(await monitor.getByRole('slider').count(), 0);
		assert.equal(await monitor.locator('.monitor-details').count(), 0);
		assert.equal(await monitor.getByRole('img').count(), 2);
		const latencyPlot = monitor.getByRole('img').first();
		assert.equal(await latencyPlot.getAttribute('viewBox'), '0 0 1100 220');
		assert.equal(await latencyPlot.locator('.request-bar').count(), 1);
		assert.equal(await latencyPlot.locator('path[data-series]').count(), 3);
		for (const [label, key] of [
			['Moyenne', 'mean_ms'],
			['P95 approximatif', 'p95_ms'],
			['Maximum', 'max_ms']
		]) {
			const legend = monitor.getByRole('button', { name: label, exact: true });
			await legend.click();
			assert.equal(await legend.getAttribute('aria-pressed'), 'false');
			assert.equal(await latencyPlot.locator(`path[data-series="${key}"]`).count(), 0);
		}
		assert.equal(await latencyPlot.locator('.request-bar').count(), 1);
		assert.ok(!(await latencyPlot.innerHTML()).includes('NaN'));
		for (const label of ['Moyenne', 'P95 approximatif', 'Maximum']) {
			const legend = monitor.getByRole('button', { name: label, exact: true });
			await legend.focus();
			await page.keyboard.press('Enter');
			assert.equal(await legend.getAttribute('aria-pressed'), 'true');
		}
		assert.equal(await latencyPlot.locator('path[data-series]').count(), 3);
		const operationRow = monitor.getByRole('row', {
			name: 'Autres 10 12 25 30 1',
			exact: true
		});
		await operationRow.waitFor();
		assert.equal(await page.getByRole('combobox', { name: 'Opérations API' }).count(), 0);
		assert.equal(await page.locator('input[type="range"]').count(), 0);
		assert.equal(
			await page.getByRole('button', { name: 'Détail des codes HTTP', exact: true }).count(),
			0
		);
		assert.ok(
			await page
				.locator('.api-monitoring')
				.evaluate(
					(monitor) =>
						!!monitor.closest('.statistics-panel') &&
						monitor.closest('.statistics-panel').lastElementChild === monitor
				)
		);
		await page.getByRole('checkbox', { name: 'Afficher en pourcentage' }).check();
		await page.setViewportSize({ width: 390, height: 844 });
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.getByRole('button', { name: 'Voir l’utilisation', exact: true }).click();
		await page
			.getByRole('dialog')
			.getByRole('heading', { name: 'Utilisation des abonnements calendrier', exact: true })
			.waitFor();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
		await page.setViewportSize({ width: 390, height: 844 });
		role = 'pupil';
		await page.goto(origin + '/me');
		assert.ok(
			await page.getByRole('button', { name: 'Copier le lien', exact: true }).isVisible()
		);
		assert.equal(await page.getByRole('button', { name: 'Générer mon lien' }).count(), 0);
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		pupilHasPromotion = false;
		await page.reload();
		assert.equal(await page.getByLabel('Votre lien personnel').count(), 0);
		assert.equal(await page.locator('.calendar-subscription').count(), 0);
		assert.ok(!(await page.content()).includes(subscriptionToken));
		role = 'admin';
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.goto(origin + '/timetable');
		await page.getByRole('link', { name: 'Salles et années scolaires' }).waitFor();
		const toggle = page.getByRole('switch', { name: 'Diffuser aux élèves PTSI annuel' });
		await toggle.click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Annuler', exact: true })
			.click();
		assert.equal(mutations.length, 0);
		assert.equal(await toggle.isChecked(), true);
		await toggle.click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Confirmer', exact: true })
			.click();
		await page.getByText('Diffusion élèves coupée', { exact: true }).waitFor();
		assert.equal(mutations.at(-1).data.confirmed_live, true);
		await toggle.click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Confirmer', exact: true })
			.click();
		await page.getByText('Diffusé aux élèves', { exact: true }).waitFor();
		await page.getByRole('button', { name: 'Nouvel agenda', exact: true }).click();
		assert.equal(await page.getByLabel('Année scolaire obligatoire').inputValue(), '2026');
		assert.equal(await page.getByLabel('Fin de journée').inputValue(), '18:55:00');
		await page.getByRole('button', { name: 'Fermer la fenêtre', exact: true }).click();
		await page.goto(origin + '/dashboard?tab=promotions&promotion=1');
		await page.getByRole('button', { name: 'Modifier les groupes', exact: true }).click();
		await page.getByRole('button', { name: 'Vue liste', exact: true }).click();
		const halfA = page.getByRole('region', { name: 'Groupe A', exact: true });
		const halfB = page.getByRole('region', { name: 'Groupe B', exact: true });
		await halfA.getByRole('button', { name: 'Élève Test', exact: true }).click();
		await halfB.getByRole('button', { name: 'Déplacer ici', exact: true }).click();
		await halfB.getByRole('button', { name: 'Élève Test', exact: true }).waitFor();
		assert.equal(
			await halfA.getByRole('button', { name: 'Élève Test', exact: true }).count(),
			0
		);
		await page.getByRole('button', { name: 'Annuler', exact: true }).click();
		await halfA.getByRole('button', { name: 'Élève Test', exact: true }).waitFor();
		assert.equal(
			await page.getByRole('button', { name: 'Créer un groupe', exact: true }).count(),
			0
		);
		await page.getByRole('button', { name: 'Groupes personnalisés', exact: true }).click();
		await page.getByRole('button', { name: 'Créer un groupe', exact: true }).click();
		await page.getByLabel('Nom', { exact: true }).fill('Allemand');
		const customDialog = page.getByRole('dialog', { name: 'Créer un groupe personnalisé' });
		await customDialog.getByRole('button', { name: 'Créer le bloc', exact: true }).click();
		const sourceClass = page.getByRole('region', { name: 'Classe entière', exact: true });
		const optionGroup = page.getByRole('region', { name: 'Allemand', exact: true });
		const saveGroup = page.getByRole('button', { name: 'Enregistrer', exact: true });
		assert.equal(await saveGroup.isDisabled(), true);
		await sourceClass
			.getByRole('button', { name: 'Élève Test', exact: true })
			.dragTo(optionGroup.getByRole('group', { name: 'Élèves de Allemand', exact: true }));
		await optionGroup.getByRole('button', { name: 'Élève Test', exact: true }).waitFor();
		assert.equal(
			await sourceClass.getByRole('button', { name: 'Élève Test', exact: true }).count(),
			1
		);
		await optionGroup.getByRole('button', { name: 'Élève Test', exact: true }).click();
		await sourceClass.getByRole('button', { name: 'Retirer du groupe', exact: true }).click();
		assert.equal(await saveGroup.isDisabled(), true);
		await sourceClass.getByRole('button', { name: 'Élève Test', exact: true }).click();
		await optionGroup.getByRole('button', { name: 'Ajouter ici', exact: true }).click();
		await optionGroup
			.getByRole('button', {
				name: 'Déplacer la bulle Allemand ; utilisez les flèches du clavier',
				exact: true
			})
			.press('ArrowRight');
		const groupSave = page.waitForResponse((response) =>
			response.url().endsWith('/dashboard/command')
		);
		await saveGroup.click();
		const groupResponse = await groupSave;
		assert.equal(groupResponse.ok(), true, await groupResponse.text());
		await page.getByText('Groupe enregistré.', { exact: true }).waitFor();
		assert.equal(customGroups[0].name, 'Allemand');
		assert.equal(customGroups[0].x, 340);
		await page.getByRole('button', { name: 'Vue liste', exact: true }).click();
		await optionGroup.getByRole('button', { name: 'Modifier', exact: true }).click();
		await page.getByLabel('Nom du groupe', { exact: true }).fill('Option allemand');
		await saveGroup.click();
		const editGroup = page.getByRole('dialog', { name: 'Modifier le groupe diffusé' });
		await editGroup
			.getByRole('button', { name: 'Confirmer la modification', exact: true })
			.click();
		await editGroup.waitFor({ state: 'detached' });
		assert.equal(mutations.at(-1).data.confirmed_live, true);
		const renamed = page.getByRole('region', { name: 'Option allemand', exact: true });
		await renamed.getByRole('button', { name: 'Supprimer', exact: true }).click();
		const deletion = page.getByRole('dialog', { name: 'Supprimer le groupe', exact: true });
		await deletion.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(customGroups.length, 1);
		await page.getByRole('button', { name: 'Demi-groupes', exact: true }).click();
		assert.equal(
			await page.getByRole('region', { name: 'Classe entière', exact: true }).count(),
			0
		);
		await page.goto(origin + '/timetable/settings');
		await page.getByRole('button', { name: 'Archivage automatique', exact: true }).click();
		const archivePolicy = page.getByRole('switch');
		assert.equal(await archivePolicy.isChecked(), true);
		await archivePolicy.uncheck();
		await page.waitForFunction(
			() => document.querySelector('[role="switch"]')?.checked === false
		);
		await archivePolicy.click();
		const archiveConfirmation = page.getByRole('dialog', {
			name: 'Activer l’archivage automatique'
		});
		await archiveConfirmation.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(await archivePolicy.isChecked(), false);
		await page.goto(origin + '/timetable/1');
		await page.locator('.ec-event:not(.ec-bg-event)').first().waitFor();
		assert.equal(await page.getByRole('button', { name: 'Publier', exact: true }).count(), 0);
		assert.equal(
			await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).count(),
			0
		);
		await page.locator('.ec-event:not(.ec-bg-event)').first().click();
		await page.getByRole('radio', { name: 'Groupes personnalisés', exact: true }).check();
		await page.getByRole('radio', { name: 'Option allemand', exact: true }).check();
		await page.getByRole('radio', { name: 'Classe entière', exact: true }).check();
		await page.getByLabel('Intitulé personnalisé').fill('Rattrapage');
		await page
			.getByRole('dialog')
			.getByRole('checkbox', { name: 'M. Partagé', exact: true })
			.check();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Enregistrer', exact: true })
			.click();
		const confirmation = page.getByRole('dialog', { name: 'Enregistrer la séance' });
		await confirmation
			.getByText('Repas : 1 élève sans une séance complète pour manger.')
			.waitFor();
		const count = mutations.length;
		await confirmation.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(mutations.length, count);
		assert.equal(await page.getByLabel('Intitulé personnalisé').inputValue(), 'Rattrapage');
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Enregistrer', exact: true })
			.click();
		await confirmation
			.getByRole('switch', { name: 'Inclure les occurrences suivantes' })
			.check();
		await confirmation
			.getByRole('switch', { name: 'Inclure les occurrences suivantes' })
			.uncheck();
		await confirmation.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await page
			.getByRole('dialog', { name: 'Enregistrer la séance' })
			.waitFor({ state: 'detached' });
		await page
			.getByRole('dialog', { name: 'Modifier la séance' })
			.waitFor({ state: 'detached' });
		assert.equal(mutations.at(-1).data.scope, 'one');
		assert.equal(mutations.at(-1).data.confirmed_live, true);
		assert.equal(mutations.at(-1).data.block.title, 'Rattrapage');
		assert.deepEqual(mutations.at(-1).data.block.teacher_ids, [2, 4]);
		assert.ok(previews.some((item) => item.data.scope === 'one'));
		const session = page.locator('.ec-event:not(.ec-bg-event)').first();
		await session.hover();
		await page.keyboard.press('Control+c');
		const nextDay = await page.locator('.ec-body .ec-day').nth(1).boundingBox();
		await page.mouse.move(nextDay.x + nextDay.width / 2, nextDay.y + 100);
		await page.keyboard.press('Control+v');
		await page.getByRole('dialog', { name: 'Nouvelle séance' }).waitFor();
		assert.equal(await page.getByLabel('Intitulé personnalisé').inputValue(), 'Rattrapage');
		assert.equal(await page.getByLabel('Date', { exact: true }).inputValue(), '2026-09-08');
		assert.equal(
			await page.getByRole('radio', { name: 'Chaque semaine', exact: true }).isChecked(),
			true
		);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
		await session.hover();
		const handle = await session.locator('.ec-resizer').last().boundingBox();
		await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
		await page.mouse.down();
		await page.mouse.move(handle.x + handle.width / 2, handle.y + 80, { steps: 10 });
		await page.mouse.up();
		await confirmation.waitFor();
		assert.ok(previews.at(-1).data.block.duration_slots > 2);
		await confirmation.getByRole('button', { name: 'Annuler', exact: true }).click();
		if (process.env.TIMETABLE_SCREENSHOT)
			await page.screenshot({ path: process.env.TIMETABLE_SCREENSHOT });
		// Holding on an empty day previews one session and creates only on release.
		const emptyDay = await page.locator('.ec-body .ec-day').nth(1).boundingBox();
		const releaseDay = await page.locator('.ec-body .ec-day').nth(2).boundingBox();
		await page.mouse.move(emptyDay.x + emptyDay.width / 2, emptyDay.y + 120);
		await page.mouse.down();
		await page.locator('.creation-preview').waitFor();
		assert.equal(await page.getByRole('dialog').count(), 0);
		await page.mouse.move(releaseDay.x + releaseDay.width / 2, releaseDay.y + 160, {
			steps: 8
		});
		await page.mouse.up();
		await page.getByRole('dialog', { name: 'Nouvelle séance' }).waitFor();
		assert.equal(await page.getByLabel('Date', { exact: true }).inputValue(), '2026-09-09');
		assert.equal(await page.getByLabel('Longueur, en séances').inputValue(), '1');
		assert.equal(
			await page.getByRole('radio', { name: 'Chaque semaine', exact: true }).isChecked(),
			true
		);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
		await page.mouse.move(emptyDay.x + emptyDay.width / 2, emptyDay.y + 120);
		await page.mouse.down();
		await page.locator('.creation-preview').waitFor();
		await page.keyboard.press('Escape');
		await page.mouse.up();
		assert.equal(await page.getByRole('dialog').count(), 0);
		await page.getByRole('button', { name: '▥ Heures', exact: true }).click();
		for (const width of [1440, 390]) {
			await page.setViewportSize({ width, height: 1000 });
			for (const mode of ['Moyenne par semaine', 'Total sur l’année']) {
				await page.getByRole('button', { name: mode, exact: true }).click();
				const rows = await page.locator('.bar-row').evaluateAll((elements) =>
					elements.map((element) => {
						const label = element.querySelector('.bar-label').getBoundingClientRect();
						const track = element.querySelector('.bar-track').getBoundingClientRect();
						const value = element.querySelector('b').getBoundingClientRect();
						return {
							labelLeft: label.left,
							labelRight: label.right,
							trackLeft: track.left,
							trackWidth: track.width,
							valueLeft: value.left,
							right: value.right,
							text: element.querySelector('b').textContent
						};
					})
				);
				assert.equal(rows.length, 3);
				for (const row of rows) {
					assert.ok(Math.abs(row.trackLeft - rows[0].trackLeft) < 1);
					assert.ok(Math.abs(row.trackWidth - rows[0].trackWidth) < 1);
					assert.ok(Math.abs(row.valueLeft - rows[0].valueLeft) < 1);
					assert.ok(row.labelLeft < row.labelRight && row.labelRight < row.trackLeft);
					assert.ok(row.trackWidth >= 40 && row.right <= width);
				}
				assert.equal(rows[0].text, mode === 'Moyenne par semaine' ? '7,89 h' : '15,78 h');
				assert.equal(rows[1].text, mode === 'Moyenne par semaine' ? '2 h' : '4 h');
			}
		}
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.getByRole('button', { name: 'Total sur l’année', exact: true }).click();
		assert.equal(
			await page
				.getByRole('button', { name: 'Total sur l’année', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
		await page.getByRole('button', { name: 'Réglages', exact: true }).click();
		assert.equal(await page.getByLabel('Début de journée', { exact: true }).isDisabled(), true);
		assert.equal(await page.getByLabel('Ouverture', { exact: true }).isDisabled(), true);
		assert.equal(await page.getByLabel('Samedi travaillé', { exact: true }).isEnabled(), true);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
		await session.click();
		await page.getByRole('switch', { name: 'Horaires libres', exact: true }).check();
		await page.getByLabel('Début libre', { exact: true }).fill('14:07:00');
		await page.getByLabel('Durée libre, en minutes', { exact: true }).fill('37.5');
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Enregistrer', exact: true })
			.click();
		await confirmation.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await confirmation.waitFor({ state: 'detached' });
		assert.equal(mutations.at(-1).data.block.start_time, 50820);
		assert.equal(mutations.at(-1).data.block.end_time, 53070);
		await page.goto(origin + '/timetable');
		await page.getByRole('button', { name: 'Archiver', exact: true }).click();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Confirmer', exact: true })
			.click();
		await page.getByRole('button', { name: 'Archives', exact: true }).click();
		await page.getByText('Archive · lecture seule', { exact: true }).waitFor();
		await page.goto(origin + '/timetable/1');
		await page
			.getByText('Archive · lecture seule · diffusion coupée', { exact: true })
			.waitFor();
		assert.equal(
			await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).count(),
			0
		);
		await page.locator('.ec-event:not(.ec-bg-event)').first().click();
		assert.equal(await page.getByLabel('Intitulé personnalisé').count(), 0);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
		await page.goto(origin + '/timetable/prof');
		assert.equal(
			await page.getByRole('combobox', { name: 'Année scolaire' }).inputValue(),
			'2026'
		);
		await page.getByRole('button', { name: 'Disponibilités', exact: true }).click();
		await page.locator('.ec-event:not(.ec-bg-event)').first().waitFor();
		assert.equal(await page.getByLabel('Minimum (h/semaine)').inputValue(), '0');
		assert.equal(await page.getByLabel('Maximum (h/semaine)').inputValue(), '0');
		assert.equal(await page.getByLabel('Minimum (h/semaine)').getAttribute('readonly'), '');
		assert.equal(await page.getByRole('button', { name: 'Enregistrer les bornes' }).count(), 0);
		await page.getByRole('button', { name: 'Éditer les disponibilités', exact: true }).click();
		await page.getByLabel('Minimum (h/semaine)').fill('1');
		await page.getByLabel('Maximum (h/semaine)').fill('3');
		const beforeFinish = mutations.length;
		await page.getByRole('button', { name: 'Actualiser', exact: true }).click();
		await page.getByLabel('Minimum (h/semaine)').waitFor();
		assert.equal(await page.getByLabel('Minimum (h/semaine)').inputValue(), '1');
		assert.equal(mutations.length, beforeFinish);
		await page.getByLabel('Maximum (h/semaine)').fill('0');
		await page.getByRole('button', { name: 'Terminer l’édition', exact: true }).click();
		await page
			.getByRole('alert')
			.filter({ hasText: 'Saisissez des heures entières' })
			.waitFor();
		assert.equal(mutations.length, beforeFinish);
		await page.getByLabel('Maximum (h/semaine)').fill('3');
		await page.getByRole('button', { name: 'Terminer l’édition', exact: true }).click();
		await page
			.getByRole('status')
			.filter({ hasText: 'Bornes de khôlles enregistrées.' })
			.waitFor();
		assert.equal(await page.getByLabel('Minimum (h/semaine)').inputValue(), '1');
		assert.equal(await page.getByLabel('Maximum (h/semaine)').inputValue(), '3');
		assert.equal(await page.getByLabel('Maximum (h/semaine)').getAttribute('readonly'), '');
		assert.equal('ranges' in mutations.at(-1).data, false);
		assert.equal(await page.locator('.ec-body .ec-day').count(), 6);
		pattern = [];
		await page.getByRole('combobox', { name: 'Année scolaire' }).selectOption('2027');
		await page.waitForFunction(
			() => document.querySelector('#kholle-min-hours')?.value === '0'
		);
		assert.equal(await page.getByLabel('Maximum (h/semaine)').inputValue(), '0');
		await page.getByRole('button', { name: 'Éditer les disponibilités', exact: true }).click();
		assert.equal(
			await page.getByRole('button', { name: 'Terminer l’édition', exact: true }).isVisible(),
			true
		);
		const staffDay = await page.locator('.ec-body .ec-day').nth(2).boundingBox();
		await page.mouse.move(staffDay.x + staffDay.width / 2, staffDay.y + 120);
		await page.mouse.down();
		await page.locator('.creation-preview').waitFor();
		await page.mouse.up();
		await page.getByLabel('Jour', { exact: true }).waitFor();
		const staffStart = (await page.getByLabel('Début', { exact: true }).inputValue())
			.split(':')
			.map(Number);
		const staffEnd = (await page.getByLabel('Fin', { exact: true }).inputValue())
			.split(':')
			.map(Number);
		assert.equal((staffEnd[0] - staffStart[0]) * 60 + staffEnd[1] - staffStart[1], 60);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Annuler', exact: true })
			.click();
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(origin + '/timetable');
		assert.ok(
			await page
				.getByRole('link', {
					name: 'prof Disponibilités et emplois du temps des enseignants'
				})
				.isVisible()
		);
		role = 'pupil';
		assert.equal((await page.goto(origin + '/timetable')).status(), 403);
		assert.equal((await page.goto(origin + '/timetable/1')).status(), 403);
		assert.equal((await page.goto(origin + '/timetable/prof')).status(), 403);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		const exited = once(child, 'exit');
		child.kill();
		await exited;
		await new Promise((resolve) => backend.close(resolve));
	}
});
