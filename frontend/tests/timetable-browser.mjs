/** Exercise the production UI against a synthetic API; PostgreSQL behavior has separate tests. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { chromium } from 'playwright';

test('separate agenda management, full-screen weekly versions, group tree and personal subscription', async () => {
	const errors = [];
	const commands = [];
	let role = 'admin';
	let authenticatedId = 1;
	let tokenExists = false;
	let feedCookie;
	let parallelCount = 1;
	let groupsDefined = true;
	let teacherUnavailable = false;
	let omitEventDetails = false;
	let rejectResize = false;
	let teachingUnavailable = false;
	let foreignBookings = false;
	let pupilCollision = false;
	let warningTemplate = null;
	const staffPatterns = new Map();
	const revision = 'a'.repeat(32);
	const settings = {
		start: '2026-09-01',
		end: '2027-06-30',
		day_start: 28800,
		day_end: 61200,
		session_minutes: 55,
		saturday: false,
		breaks: [
			{ start: 35400, end: 36600 },
			{ start: 43200, end: 46800 },
			{ start: 53400, end: 54600 }
		],
		holidays: []
	};
	const slots = [
		...Array.from({ length: 4 }, (_, index) => [28800 + index * 1650, 30450 + index * 1650]),
		...Array.from({ length: 4 }, (_, index) => [36600 + index * 1650, 38250 + index * 1650]),
		...Array.from({ length: 4 }, (_, index) => [46800 + index * 1650, 48450 + index * 1650]),
		...Array.from({ length: 4 }, (_, index) => [54600 + index * 1650, 56250 + index * 1650])
	];
	const block = {
		id: revision,
		lineage: revision,
		template_key: revision,
		starts_on: '2026-09-07',
		start_slot: 0,
		duration_slots: 8,
		subject_id: 1,
		teacher_id: 2,
		room_id: 1,
		kind: 'course',
		title: 'Mathématiques <img src=x onerror="document.body.dataset.calendarXss=1">',
		interval: 1,
		until: null,
		exceptions: {}
	};
	let agendas = [
		{
			id: 1,
			name: 'Première année',
			promotion_id: 1,
			revision,
			is_paused: false,
			years: [{ id: 1, school_year: 2026, revision }]
		}
	];
	let rooms = [{ id: 1, name: 'B402', revision }];
	const commonYears = [{ school_year: 2026, settings, revision, alternatives: [] }];
	let patterns = [
		{
			key: revision,
			weekday: 0,
			phase: 1,
			interval: 1,
			start_slot: 0,
			duration_slots: 8,
			subject_id: 1,
			teacher_id: 2,
			room_id: 1,
			kind: 'course',
			title: ''
		}
	];
	const versions = [];
	const backend = createServer(async (request, response) => {
		const url = new URL(request.url, 'http://localhost');
		response.setHeader('Content-Type', 'application/json');
		const reply = (body) => response.end(JSON.stringify(body));
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
				id: authenticatedId,
				username: 'test',
				first_name: 'Camille',
				last_name: 'Test',
				is_bootstrap: false,
				status: 'active',
				roles:
					role === 'admin' && authenticatedId === 6
						? ['admin', 'teacher']
						: [role === 'pupil' ? 'user' : role],
				permissions:
					role === 'admin'
						? ['users.manage', 'users.read', 'promotions.manage']
						: role === 'teacher'
							? ['teaching.read', 'teacher.access']
							: ['user.access']
			});
		if (url.pathname === '/api/v1/auth/me/profile') return reply(null);
		if (url.pathname === '/api/v1/timetable/staff/catalog')
			return reply({
				administrator: role === 'admin',
				today: '2026-09-07',
				teachers: [
					{ id: 2, name: 'Mme Test', subject_ids: [1] },
					{ id: 6, name: 'Zoé Maths', subject_ids: [1] },
					{ id: 5, name: 'Alice Autre', subject_ids: [2] }
				],
				subjects: [
					{ id: 1, name: 'Mathématiques', color: '#244BC1' },
					{ id: 2, name: 'Physique', color: '#a04020' }
				],
				years: [{ school_year: 2026, settings, slots }]
			});
		if (url.pathname === '/api/v1/timetable/staff/board') {
			const ids = url.searchParams.get('teacher_ids').split(',').map(Number);
			const opening = Array.from({ length: 5 }, (_, weekday) => [
				{ weekday, start: 28800, end: 35400 },
				{ weekday, start: 36600, end: 43200 },
				{ weekday, start: 46800, end: 53400 },
				{ weekday, start: 54600, end: 61200 }
			]).flat();
			return reply({
				occupied_ranges:
					url.searchParams.get('include_occupancy') === 'true'
						? [{ weekday: 0, start: 28800, end: 32100 }]
						: [],
				availability: ids.map((id) => ({
					teacher_id: id,
					revision: staffPatterns.has(id) ? revision : null,
					default: !staffPatterns.has(id),
					ranges: staffPatterns.get(id) ?? opening
				})),
				events: ids.flatMap((id) =>
					['course', 'td', 'tp', 'kholle'].map((kind, index) => ({
						...block,
						id: `staff-${id}-${index}`,
						series_id: `staff-${id}-${index}`,
						school_year: 2026,
						start: `2026-09-07T${index + 8}:00:00+02:00`
							.replace('T8:', 'T08:')
							.replace('T9:', 'T09:'),
						end: `2026-09-07T${index + 8}:55:00+02:00`
							.replace('T8:', 'T08:')
							.replace('T9:', 'T09:'),
						kind,
						audience_label: [
							'Classe entière',
							'Demi-groupe A',
							'Tiers de groupe X',
							'Groupe de khôlle 001'
						][index],
						teacher_id: id,
						teacher: id === 2 ? 'Mme Test' : 'Zoé Maths',
						room: 'B402',
						calendar_id: index < 2 ? 1 : 2,
						year_id: 1,
						promotion_id: null,
						calendar_label: index < 2 ? 'PTSI 2026' : 'Deuxième année',
						color: '#244BC1',
						title: kind
					}))
				)
			});
		}
		if (url.pathname === '/api/v1/auth/me/promotions') return reply([]);
		if (url.pathname === '/api/v1/timetable/catalog')
			return reply({
				administrator: role === 'admin',
				today: '2026-09-07',
				calendars: agendas,
				common_years: commonYears,
				promotions: [{ id: 1, name: 'PTSI 2026' }],
				teachers: teacherUnavailable
					? []
					: [
							{ id: 5, name: 'Alice Autre', subject_ids: [2], roles: ['teacher'] },
							{
								id: 6,
								name: 'Zoé Maths',
								subject_ids: [1],
								roles: ['teacher', 'kholleur']
							},
							{
								id: 2,
								name: 'Mme Test',
								subject_ids: [1],
								roles: ['teacher', 'kholleur']
							},
							{ id: 8, name: 'Khôlleur seul', subject_ids: [1], roles: ['kholleur'] }
						],
				subjects: [
					{ id: 1, name: 'Mathématiques', color: '#244BC1' },
					{ id: 2, name: 'Physique', color: '#a04020' }
				],
				rooms
			});
		if (url.pathname === '/api/v1/timetable/board')
			return reply({
				calendars: agendas,
				years: [
					{
						id: 1,
						calendar_id: 1,
						school_year: 2026,
						settings,
						slots,
						revision,
						published_revision: revision,
						weeks: { '2026-09-07': 2 },
						series: role === 'admin' ? [block] : [],
						template_blocks: patterns
					}
				],
				warnings: [],
				teacher_commitments: foreignBookings
					? [
							{
								teacher_id: 2,
								calendar_id: 2,
								calendar_label: 'Deuxième année',
								year_id: 2,
								series_id: 'foreign-series',
								conflict_key: 'foreign-key',
								source_date: '2026-09-07',
								start: '2026-09-07T08:00:00+02:00',
								end: '2026-09-07T09:50:00+02:00'
							}
						]
					: [],
				availability: teachingUnavailable
					? [{ teacher_id: 2, school_year: 2026, ranges: [] }]
					: [],
				members: [3, 4].map((id) => ({
					id,
					name: id === 3 ? 'Élève Alpha' : 'Élève Beta',
					roles: ['user'],
					promotion_ids: [1],
					assignments: ['halves', 'thirds', 'kholles'].map((kind) => ({
						promotion_id: 1,
						kind,
						number: id - 2
					}))
				})),
				groups: groupsDefined
					? ['halves', 'thirds', 'kholles'].flatMap((kind) =>
							[1, 2].map((number) => ({
								promotion_id: 1,
								kind,
								number,
								student_ids: [number + 2]
							}))
						)
					: [],
				events: [
					...[
						['08:00:00', '09:50:00'],
						['10:10:00', '12:00:00']
					].flatMap(([start, end], index) =>
						Array.from({ length: parallelCount }, (_, column) => ({
							...block,
							id: `${revision}-2026-09-07-${index}-${column}`,
							series_id: revision,
							source_date: '2026-09-07',
							start: `2026-09-07T${start}+02:00`,
							end: `2026-09-07T${end}+02:00`,
							teacher: omitEventDetails ? '' : 'Mme Test',
							teacher_roles: ['teacher', 'kholleur'],
							room: omitEventDetails ? '' : 'B402',
							color: '#244BC1',
							year_id: 1,
							calendar_id: 1,
							promotion_id: 1
						}))
					),
					{
						...block,
						id: 'private',
						template_key: null,
						start_slot: pupilCollision ? 0 : 8,
						duration_slots: 2,
						kind: 'kholle',
						series_id: 'b'.repeat(32),
						source_date: '2026-09-07',
						start: pupilCollision
							? '2026-09-07T08:00:00+02:00'
							: '2026-09-07T13:00:00+02:00',
						end: pupilCollision
							? '2026-09-07T08:55:00+02:00'
							: '2026-09-07T13:55:00+02:00',
						teacher: 'Mme Test',
						teacher_roles: ['teacher', 'kholleur'],
						room: 'B402',
						color: '#244BC1',
						year_id: 1,
						calendar_id: 1,
						promotion_id: 1,
						target_kind: 'student',
						target_user_id: 4,
						title: 'Séance individuelle'
					},
					...(warningTemplate
						? [
								{
									...block,
									id: 'warning-template-event',
									series_id: 'warning-template-series',
									template_key: warningTemplate.key,
									source_date: '2026-09-08',
									start: '2026-09-08T08:00:00+02:00',
									end: '2026-09-08T08:55:00+02:00',
									start_slot: 0,
									duration_slots: 2,
									kind: 'tp',
									title: 'Séance repère',
									teacher: 'Mme Test',
									teacher_roles: ['teacher', 'kholleur'],
									room: 'B402',
									color: '#244BC1',
									year_id: 1,
									calendar_id: 1,
									promotion_id: 1
								}
							]
						: [])
				]
			});
		if (url.pathname === '/api/v1/timetable/configuration' && request.method === 'GET')
			return reply({ years: commonYears, rooms });
		if (url.pathname.endsWith('/template') && request.method === 'GET')
			return reply({ revision, blocks: patterns, versions });
		if (url.pathname === '/api/v1/timetable/subscription') {
			if (request.method === 'GET') return reply({ exists: tokenExists });
			tokenExists = true;
			return reply({ token: 'A'.repeat(43) });
		}
		if (url.pathname.startsWith('/api/v1/timetable/feed/')) {
			feedCookie = request.headers.cookie;
			response.setHeader('Content-Type', 'text/calendar');
			return response.end('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n');
		}
		if (['POST', 'PUT', 'DELETE'].includes(request.method)) {
			if (rejectResize) {
				response.statusCode = 409;
				return reply({ detail: 'L’agenda a changé. Rechargez-le avant de continuer.' });
			}
			let body = '';
			for await (const chunk of request) body += chunk;
			const payload = JSON.parse(body);
			commands.push({ path: url.pathname, body: payload });
			if (/\/staff\/\d+\/\d+\/availability$/.test(url.pathname)) {
				const id = Number(url.pathname.split('/').at(-2));
				if (payload.ranges === null) staffPatterns.delete(id);
				else staffPatterns.set(id, payload.ranges);
				return reply({ revision });
			}
			if (url.pathname === '/api/v1/timetable/calendars') {
				const id = agendas.length + 1;
				agendas.push({ id, ...payload, revision, years: [] });
				return reply({ id, revision });
			}
			if (/\/calendars\/\d+$/.test(url.pathname)) {
				const id = Number(url.pathname.split('/').at(-1));
				if (request.method === 'DELETE') agendas = agendas.filter((item) => item.id !== id);
				else
					agendas = agendas.map((item) =>
						item.id === id ? { ...item, ...payload } : item
					);
				return reply({ id, revision });
			}
			if (url.pathname === '/api/v1/timetable/rooms') {
				const id = rooms.length + 1;
				rooms.push({ id, name: payload.name, revision });
				return reply({ id, revision });
			}
			if (/\/rooms\/\d+$/.test(url.pathname)) {
				const id = Number(url.pathname.split('/').at(-1));
				if (request.method === 'DELETE') rooms = rooms.filter((item) => item.id !== id);
				else
					rooms = rooms.map((item) =>
						item.id === id ? { ...item, name: payload.name } : item
					);
				return reply({ id, revision });
			}
			if (url.pathname.endsWith('/template')) {
				if (JSON.stringify(patterns) === JSON.stringify(payload.blocks))
					return reply({
						revision,
						number: versions.at(-1)?.number ?? null,
						changed: false
					});
				patterns = payload.blocks;
				versions.push({
					number: versions.length + 1,
					effective_on: payload.effective_at?.slice(0, 10) ?? '2026-09-07',
					effective_at: payload.effective_at ?? '2026-09-07T12:00:00Z'
				});
				return reply({
					revision,
					number: versions.length,
					changed: true,
					effective_at: versions.at(-1).effective_at
				});
			}
			return reply({ revision });
		}
		response.writeHead(404).end();
	});
	await new Promise((resolve) => backend.listen(0, '127.0.0.1', resolve));
	const child = spawn(
		process.execPath,
		[
			'--input-type=module',
			'-e',
			"import { createServer } from 'node:http'; let handler; const server = createServer((req, res) => handler(req, res)); server.listen(0, '127.0.0.1', async () => { process.env.ORIGIN = 'http://127.0.0.1:' + server.address().port; ({ handler } = await import('./build/handler.js')); console.log('PORT=' + server.address().port); });"
		],
		{
			cwd: new URL('..', import.meta.url),
			windowsHide: true,
			stdio: ['ignore', 'pipe', 'pipe'],
			env: {
				...process.env,
				NODE_ENV: 'production',
				BACKEND_ORIGIN: `http://127.0.0.1:${backend.address().port}`
			}
		}
	);
	let output = '';
	child.stderr.on('data', (chunk) => (output += chunk));
	let browser;
	try {
		const origin = await new Promise((resolve, reject) => {
			const timer = setTimeout(() => reject(new Error(`Startup timeout: ${output}`)), 15000);
			child.once('error', reject);
			child.stdout.on('data', (chunk) => {
				output += chunk;
				const port = output.match(/PORT=(\d+)/)?.[1];
				if (port) {
					clearTimeout(timer);
					resolve(`http://127.0.0.1:${port}`);
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
		await page.clock.setFixedTime(new Date('2026-09-07T12:00:00Z'));
		page.on('pageerror', (error) => errors.push(error.message));
		await page.goto(`${origin}/timetable`);
		assert.equal(await page.locator('.ec').count(), 0);
		const permanent = page.locator('.agenda-row').filter({ hasText: 'Agenda permanent' });
		assert.equal(await permanent.getByRole('button').count(), 0);
		assert.equal(await permanent.getByRole('switch').count(), 0);
		await permanent.getByRole('link').click();
		await page.locator('.ec-event').first().waitFor();
		assert.equal(await page.locator('.site-header').count(), 0);
		assert.equal(
			await page
				.getByRole('button', { name: 'Emploi du temps', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		assert.equal(
			await page
				.getByRole('button', { name: 'Mme Test', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		assert.equal(await page.locator('.ec-event.timetable-kholle').count(), 1);
		assert.deepEqual(await page.locator('.timetable-event-audience').allTextContents(), [
			'Cours · Classe entière',
			'TD · Demi-groupe A',
			'TP · Tiers de groupe X',
			'Khôlle · Groupe de khôlle 001'
		]);
		assert.deepEqual(await page.locator('.timetable-event-calendar').allTextContents(), [
			'PTSI 2026',
			'PTSI 2026',
			'Deuxième année',
			'Deuxième année'
		]);
		const calendarColors = await page
			.locator('.ec-event')
			.evaluateAll((elements) =>
				elements.map((element) => getComputedStyle(element).backgroundColor)
			);
		assert.equal(calendarColors[0], calendarColors[1]);
		assert.equal(calendarColors[2], calendarColors[3]);
		assert.notEqual(calendarColors[0], calendarColors[2]);
		assert.ok(
			(
				await page
					.locator('.ec-event.timetable-kholle')
					.evaluate((element) => getComputedStyle(element).backgroundImage)
			).includes('repeating-linear-gradient')
		);
		assert.equal(
			await page
				.locator('.ec-event:not(.timetable-kholle)')
				.first()
				.evaluate((element) => getComputedStyle(element).backgroundImage),
			'none'
		);
		authenticatedId = 6;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		assert.equal(
			await page
				.getByRole('button', { name: 'Zoé Maths', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		role = 'teacher';
		authenticatedId = 5;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		assert.equal(
			await page
				.getByRole('button', { name: 'Alice Autre', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		assert.equal(
			await page
				.getByRole('button', { name: 'Emploi du temps', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		assert.equal(
			await page
				.getByRole('button', { name: 'Éditer les disponibilités', exact: true })
				.count(),
			0
		);
		role = 'admin';
		authenticatedId = 1;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		await page.getByRole('button', { name: 'Disponibilités', exact: true }).click();
		await page.locator('.ec-event[data-timetable-event-id^="availability-"]').first().waitFor();
		assert.equal(await page.locator('.ec-event').count(), 20);
		await page.locator('.ec-bg-event.timetable-occupied').waitFor();
		assert.equal(
			await page
				.locator('.ec-bg-event.timetable-occupied')
				.evaluate((element) => getComputedStyle(element).pointerEvents),
			'none'
		);
		assert.ok(
			await page
				.locator('.ec-bg-event.timetable-occupied')
				.evaluate(
					(element) =>
						getComputedStyle(element).backgroundImage.includes('45deg') &&
						getComputedStyle(element).opacity === '1'
				)
		);
		assert.ok(
			await page
				.locator('.ec-bg-event:not(.timetable-occupied)')
				.first()
				.evaluate((element) => getComputedStyle(element).backgroundImage.includes('135deg'))
		);
		assert.equal(
			await page
				.locator('.ec-event')
				.first()
				.evaluate((element) => getComputedStyle(element).opacity),
			'1'
		);
		assert.ok(
			await page
				.locator('.ec-event')
				.first()
				.evaluate((element) => getComputedStyle(element).backgroundColor.includes('0.8'))
		);
		assert.equal(await page.locator('.timetable-event-audience').count(), 0);
		assert.equal(await page.locator('.ec-event em.timetable-event-teacher').count(), 20);
		assert.equal(await page.locator('.ec-event strong.timetable-event-name').count(), 20);
		assert.ok((await page.locator('.ec-header').innerText()).includes('lundi'));
		assert.equal(await page.getByLabel('Date consultée').count(), 0);
		if (process.env.PROF_SCREENSHOT)
			await page.screenshot({ path: process.env.PROF_SCREENSHOT });
		await page.getByRole('button', { name: 'Éditer les disponibilités', exact: true }).click();
		assert.equal(await page.locator('.ec-bg-event.timetable-occupied').count(), 1);
		const firstAvailabilitySave = page.waitForResponse(
			(response) =>
				response.request().method() === 'POST' &&
				response.url().includes('/timetable/prof/data')
		);
		await page.getByRole('button', { name: 'Toute la semaine indisponible' }).click();
		const availabilityResponse = await firstAvailabilitySave;
		assert.equal(availabilityResponse.status(), 200, await availabilityResponse.text());
		await page
			.getByRole('status')
			.filter({ hasText: 'Disponibilités enregistrées.' })
			.waitFor();
		assert.equal(await page.locator('.ec-event').count(), 0);
		assert.equal(await page.locator('.ec-bg-event.timetable-occupied').count(), 1);
		await page.getByRole('button', { name: 'Ajouter une plage', exact: true }).click();
		const availabilityDialog = page.locator('dialog');
		await availabilityDialog.getByLabel('Début', { exact: true }).fill('08:00:00');
		await availabilityDialog.getByLabel('Fin', { exact: true }).fill('09:50:00');
		await availabilityDialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await availabilityDialog.waitFor({ state: 'hidden' });
		await page.locator('.ec-event').first().waitFor();
		const availabilityBox = await page.locator('.ec-event').first().boundingBox();
		const availabilityHour =
			(await page.locator('.ec-body .ec-day').first().boundingBox()).height / 9;
		const resized = page.waitForResponse(
			(response) =>
				response.request().method() === 'POST' &&
				response.url().includes('/timetable/prof/data')
		);
		await page.mouse.move(
			availabilityBox.x + availabilityBox.width / 2,
			availabilityBox.y + availabilityBox.height - 2
		);
		await page.mouse.down();
		await page.mouse.move(
			availabilityBox.x + availabilityBox.width / 2,
			availabilityBox.y + availabilityBox.height - 2 - availabilityHour,
			{ steps: 12 }
		);
		await page.mouse.up();
		assert.equal((await resized).status(), 200);
		assert.ok(
			commands.findLast((command) => command.path.endsWith('/availability')).body.ranges[0]
				.end < 35400
		);
		await page
			.getByRole('button', { name: 'Terminer l’édition' })
			.and(page.locator(':enabled'))
			.waitFor();
		await page.getByRole('button', { name: 'Terminer l’édition' }).click();
		await page.keyboard.down('ControlLeft');
		await page.getByRole('button', { name: 'Zoé Maths', exact: true }).click();
		await page.keyboard.up('ControlLeft');
		await page.getByLabel('Date consultée').waitFor();
		await page.locator('.ec-event').nth(7).waitFor();
		assert.equal(await page.locator('.ec-bg-event.timetable-occupied').count(), 0);
		assert.equal(
			await page
				.getByRole('button', { name: 'Éditer les disponibilités', exact: true })
				.count(),
			0
		);
		assert.equal(
			await page.getByRole('button', { name: 'Disponibilités', exact: true }).isDisabled(),
			true
		);
		await page.getByRole('button', { name: 'Heures', exact: true }).click();
		await page
			.locator('dialog')
			.getByText('Afficher les données du graphique', { exact: true })
			.click();
		assert.equal(
			await page
				.locator('dialog')
				.getByRole('row')
				.filter({ hasText: 'Mathématiques' })
				.getByRole('cell')
				.nth(3)
				.innerText(),
			'2 h'
		);
		await page.locator('dialog').getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page
			.getByRole('button', { name: /Mathématiques/, exact: false })
			.first()
			.click();
		assert.equal(
			await page
				.getByRole('button', { name: 'Mme Test', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		assert.equal(
			await page
				.getByRole('button', { name: 'Zoé Maths', exact: true })
				.getAttribute('aria-pressed'),
			'true'
		);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.getByRole('button', { name: 'Afficher les enseignants' }).click();
		assert.equal(
			await page.getByLabel('Rechercher un enseignant ou une matière').isVisible(),
			true
		);
		assert.ok(
			await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		);
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.goto(`${origin}/timetable`);
		await page.getByRole('button', { name: 'Nouvel agenda', exact: true }).click();
		const dialog = page.locator('dialog');
		await dialog.getByLabel('Nom de l’agenda').fill('Deuxième année');
		await dialog.getByLabel('Promotion affectée').selectOption('1');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.locator('.agenda-row').filter({ hasText: 'Deuxième année' }).waitFor();
		assert.equal(await page.locator('.agenda-row').count(), 3);
		await page
			.locator('.agenda-row')
			.filter({ hasText: 'Deuxième année' })
			.getByRole('button', { name: 'Supprimer', exact: true })
			.click();
		await dialog.getByRole('button', { name: 'Supprimer l’agenda', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page
			.locator('.agenda-row')
			.filter({ hasText: 'Deuxième année' })
			.waitFor({ state: 'hidden' });
		await page.getByRole('switch').click();
		await page.getByText('En pause', { exact: true }).waitFor();
		await page.getByRole('switch').click();
		await page.getByText('Actif', { exact: true }).waitFor();
		await page.getByRole('link', { name: 'Réglages communs' }).click();
		await page.getByRole('button', { name: 'Salles', exact: true }).click();
		await page.getByRole('button', { name: 'Ajouter une salle' }).click();
		await dialog.getByLabel('Nom de la salle').fill('C101');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page
			.locator('.room-row')
			.filter({ hasText: 'C101' })
			.getByRole('button', { name: 'Modifier' })
			.click();
		await dialog.getByLabel('Nom de la salle').fill('C102');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page
			.locator('.room-row')
			.filter({ hasText: 'C102' })
			.getByRole('button', { name: 'Supprimer' })
			.click();
		await dialog.getByRole('button', { name: 'Supprimer la salle' }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByRole('link', { name: '← Agendas', exact: true }).click();
		await page.locator('button.agenda-open').first().click();
		await page.locator('.ec-event').first().waitFor();
		assert.equal(await page.locator('.ec-event').count(), 3);
		assert.equal(
			await page.locator('.timetable-event-audience').first().innerText(),
			'Cours · Classe entière'
		);
		assert.equal(await page.locator('.ec-event.timetable-kholle').count(), 1);
		assert.equal(await page.locator('.warning-button.clear').count(), 1);
		assert.equal(await page.locator('.site-header').count(), 0);
		assert.equal(await page.locator('.site-footer').count(), 0);
		assert.ok(
			Math.abs((await page.locator('.calendar-workspace').boundingBox()).height - 1000) <= 1
		);
		assert.equal(await page.locator('.ec-event img').count(), 0);
		assert.equal(await page.evaluate(() => document.body.dataset.calendarXss), undefined);
		assert.ok(
			await page
				.locator('.ec-event')
				.first()
				.evaluate((element) => {
					const style = getComputedStyle(element);
					const name = element.querySelector('.timetable-event-name');
					const teacher = element.querySelector('.timetable-event-teacher');
					const bounds = element.getBoundingClientRect();
					const title = element.querySelector('.ec-event-title');
					return (
						style.borderTopWidth === '0px' &&
						style.boxShadow.includes('inset') &&
						style.boxShadow.includes('2px') &&
						getComputedStyle(name).fontWeight === '700' &&
						getComputedStyle(teacher).fontStyle === 'italic' &&
						getComputedStyle(title).position === 'static' &&
						getComputedStyle(title).textAlign === 'left' &&
						Math.abs(name.getBoundingClientRect().top - bounds.top - 6) < 1
					);
				})
		);
		const initialDay = await page.locator('.ec-body .ec-day').first().boundingBox();
		const initialEvent = await page.locator('.ec-event').first().boundingBox();
		assert.ok(
			Math.abs(initialDay.x + initialDay.width - initialEvent.x - initialEvent.width - 12) < 2
		);
		await page.mouse.click(initialDay.x + initialDay.width - 5, initialEvent.y + 12);
		await dialog.waitFor();
		assert.equal(await dialog.getByLabel('Début', { exact: true }).inputValue(), '08:00:00');
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		omitEventDetails = true;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		assert.equal(
			await page.locator('.ec-event').first().locator('.timetable-event-teacher').count(),
			0
		);
		assert.equal(
			await page.locator('.ec-event').first().locator('.ec-event-title > *').count(),
			3
		);
		assert.ok(
			Math.abs(
				(await page.locator('.ec-event').first().boundingBox()).height - initialEvent.height
			) < 1
		);
		omitEventDetails = false;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		assert.equal(
			await page.locator('.ec-event').first().locator('.ec-event-title > *').count(),
			4
		);
		assert.ok(
			Math.abs(
				(await page.locator('.ec-event').first().boundingBox()).height - initialEvent.height
			) < 1
		);
		assert.ok(await page.getByText('08 h', { exact: true }).count());
		assert.equal(await page.getByText('08:27:30', { exact: true }).count(), 0);
		assert.ok(
			(
				await page
					.locator('.ec-body .ec-day')
					.first()
					.evaluate((day) => getComputedStyle(day).backgroundImage)
			).includes('repeating-linear-gradient')
		);
		for (const count of [2, 3]) {
			parallelCount = count;
			await page.reload();
			await page
				.locator('.ec-event')
				.nth(count * 2)
				.waitFor();
			const boxes = await page.locator('.ec-event').evaluateAll((elements) =>
				elements.map((element) => {
					const bounds = element.getBoundingClientRect();
					return { x: bounds.x, y: bounds.y, right: bounds.right, width: bounds.width };
				})
			);
			const firstRow = boxes
				.filter((box) => Math.abs(box.y - boxes[0].y) < 1)
				.sort((a, b) => a.x - b.x);
			assert.equal(firstRow.length, count);
			const dayWidth = (await page.locator('.ec-body .ec-day').first().boundingBox()).width;
			for (let index = 0; index < firstRow.length; index++) {
				assert.ok(Math.abs(firstRow[index].width - (dayWidth - 12) / count) < 2);
				if (index) assert.ok(firstRow[index - 1].right <= firstRow[index].x + 1);
			}
			assert.ok(
				await page
					.locator('.ec-event-title')
					.first()
					.evaluate((element) => {
						const bounds = element.getBoundingClientRect();
						const parent = element.closest('.ec-event').getBoundingClientRect();
						return (
							bounds.right <= parent.right &&
							getComputedStyle(element).overflow === 'hidden'
						);
					})
			);
		}
		parallelCount = 1;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		await page.evaluate(() => (document.documentElement.dataset.theme = 'dark'));
		const todayContrast = await page
			.locator('.ec-header .ec-today')
			.first()
			.evaluate((element) => {
				const style = getComputedStyle(element);
				const canvas = document.createElement('canvas');
				canvas.width = canvas.height = 1;
				const context = canvas.getContext('2d');
				const luminance = (color) => {
					context.fillStyle = color;
					context.fillRect(0, 0, 1, 1);
					const rgb = [...context.getImageData(0, 0, 1, 1).data]
						.slice(0, 3)
						.map((part) => {
							const value = part / 255;
							return value <= 0.04045
								? value / 12.92
								: ((value + 0.055) / 1.055) ** 2.4;
						});
					return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
				};
				const ink = luminance(style.color);
				const background = luminance(style.backgroundColor);
				return (Math.max(ink, background) + 0.05) / (Math.min(ink, background) + 0.05);
			});
		assert.ok(todayContrast >= 4.5, `Current date contrast: ${todayContrast}`);
		const pause = page.locator('.ec-bg-event').filter({ hasText: 'Pause' }).first();
		assert.ok(
			await pause.evaluate((element) => {
				const style = getComputedStyle(element);
				const bounds = element.getBoundingClientRect();
				const text = element.querySelector('.ec-event-title').getBoundingClientRect();
				return (
					style.backgroundImage.includes('repeating-linear-gradient') &&
					Math.abs(text.x + text.width / 2 - bounds.x - bounds.width / 2) < 2 &&
					Math.abs(text.y + text.height / 2 - bounds.y - bounds.height / 2) < 2
				);
			})
		);
		await page.evaluate(() => (document.documentElement.dataset.theme = 'light'));
		await page.getByRole('button', { name: 'Demi-groupe A', exact: true }).click();
		assert.equal(await page.locator('.ec-event').count(), 2);
		await page.getByLabel('Rechercher un élève', { exact: true }).fill('Beta');
		assert.equal(
			await page.getByRole('button', { name: 'Élève Beta', exact: true }).count(),
			3
		);
		await page.getByRole('button', { name: 'Élève Beta', exact: true }).first().click();
		assert.equal(await page.locator('.ec-event').count(), 3);
		await page.getByLabel('Rechercher un élève', { exact: true }).fill('');
		assert.equal(
			await page.locator('.resource-tree').getByText('Mme Test', { exact: true }).count(),
			0
		);
		await page.getByRole('button', { name: 'PTSI 2026', exact: true }).click();
		if (process.env.TIMETABLE_SCREENSHOT)
			await page.screenshot({ path: process.env.TIMETABLE_SCREENSHOT });
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).click();
		await page.getByRole('button', { name: 'Quitter', exact: true }).waitFor();
		assert.equal(await page.locator('.ec-event.timetable-kholle').count(), 0);
		assert.equal(await page.locator('.resource-sidebar').count(), 0);
		assert.equal(await dialog.count(), 0);
		assert.equal(
			await page.getByLabel('Date et heure d’application', { exact: true }).count(),
			0
		);
		const day = page.locator('.ec-body .ec-day').nth(1);
		const bounds = await day.boundingBox();
		await page.mouse.click(
			bounds.x + bounds.width / 2,
			bounds.y + (131 / 60) * (bounds.height / 9)
		);
		await dialog.waitFor();
		assert.equal(await dialog.getByLabel('Début', { exact: true }).inputValue(), '10:10:00');
		assert.equal(await dialog.locator('select').count(), 0);
		assert.equal(await dialog.getByRole('radio', { name: 'Khôlle', exact: true }).count(), 0);
		for (const name of ['Matière', 'Enseignant', 'Salle']) {
			assert.equal(
				await dialog
					.getByRole('group', { name, exact: true })
					.getByRole('radio', { checked: true })
					.count(),
				0
			);
		}
		const teacherOrder = () =>
			dialog
				.getByRole('group', { name: 'Enseignant', exact: true })
				.locator('.tag-choice > span:first-of-type')
				.allTextContents();
		assert.ok(
			await dialog
				.getByRole('button', { name: 'Enregistrer', exact: true })
				.evaluate(
					(button) =>
						button.getBoundingClientRect().top <
						button.form.querySelector('fieldset').getBoundingClientRect().top
				)
		);
		const saveTop = await dialog
			.getByRole('button', { name: 'Enregistrer', exact: true })
			.boundingBox();
		await dialog
			.locator('.dialog-body')
			.evaluate((body) => (body.scrollTop = body.scrollHeight));
		const saveAfterScroll = await dialog
			.getByRole('button', { name: 'Enregistrer', exact: true })
			.boundingBox();
		assert.equal(saveAfterScroll.y, saveTop.y);
		assert.ok(
			await dialog
				.locator('.dialog-toolbar')
				.evaluate(
					(toolbar) =>
						Math.abs(
							toolbar.getBoundingClientRect().bottom -
								toolbar.nextElementSibling.getBoundingClientRect().top
						) < 1
				)
		);
		await dialog.locator('.dialog-body').evaluate((body) => (body.scrollTop = 0));
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).click();
		assert.equal(
			await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).isChecked(),
			false
		);
		await dialog.getByRole('radio', { name: 'Mme Test', exact: true }).click();
		await dialog.getByRole('radio', { name: 'Mme Test', exact: true }).click();
		assert.equal(
			await dialog.getByRole('radio', { name: 'Mme Test', exact: true }).isChecked(),
			false
		);
		await dialog.getByRole('radio', { name: 'B402', exact: true }).focus();
		await page.keyboard.press('Space');
		await page.keyboard.press('Space');
		assert.equal(
			await dialog.getByRole('radio', { name: 'B402', exact: true }).isChecked(),
			false
		);
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.getByRole('alert').filter({ hasText: 'intitulé personnalisé' }).waitFor();
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).fill('   ');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		assert.equal(await dialog.isVisible(), true);
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		assert.deepEqual(await teacherOrder(), ['Mme Test', 'Zoé Maths', 'Alice Autre']);
		assert.equal(
			await dialog.getByRole('radio', { name: 'Khôlleur seul', exact: true }).count(),
			0
		);
		assert.match(
			await dialog
				.getByRole('radio', { name: 'Alice Autre', exact: true })
				.locator('..')
				.getAttribute('class'),
			/\bsecondary\b/
		);
		await dialog.getByRole('radio', { name: 'Physique', exact: true }).check();
		assert.deepEqual(await teacherOrder(), ['Alice Autre', 'Mme Test', 'Zoé Maths']);
		assert.equal(
			await dialog
				.getByRole('group', { name: 'Enseignant', exact: true })
				.locator('.tag-choice.secondary')
				.count(),
			2
		);
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + 5 * (bounds.height / 9) + 6);
		await dialog.waitFor();
		await dialog.getByLabel('Début', { exact: true }).fill('08:30:00');
		await dialog.getByLabel('Longueur, en séances').fill('1.5');
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).fill('Séance test');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).focus();
		await page.keyboard.press('Enter');
		await dialog.waitFor();
		assert.equal(await dialog.getByLabel('Longueur, en séances').inputValue(), '1');
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		const copiedEvent = page.locator('.ec-event').filter({ hasText: 'Séance test' }).first();
		await copiedEvent.click({ button: 'right' });
		await page.getByRole('menuitem', { name: /Copier la séance/ }).click();
		const pasteBounds = await page.locator('.ec-body .ec-day').nth(2).boundingBox();
		await page.mouse.move(
			pasteBounds.x + pasteBounds.width / 2,
			pasteBounds.y + 5 * (pasteBounds.height / 9) + 6
		);
		await page.keyboard.press('Control+v');
		await dialog.waitFor();
		assert.equal(
			await dialog.getByLabel('Intitulé personnalisé', { exact: true }).inputValue(),
			'Séance test'
		);
		assert.equal(await dialog.getByLabel('Longueur, en séances').inputValue(), '1.5');
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).fill('Copie test');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await copiedEvent.hover();
		await page.keyboard.press('Control+c');
		await page.mouse.click(
			pasteBounds.x + pasteBounds.width / 2,
			pasteBounds.y + 6 * (pasteBounds.height / 9) + 6,
			{ button: 'right' }
		);
		await page.getByRole('menuitem', { name: /Coller ici/ }).click();
		await dialog.waitFor();
		assert.equal(
			await dialog.getByLabel('Intitulé personnalisé', { exact: true }).inputValue(),
			'Séance test'
		);
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).focus();
		await page.keyboard.press('Control+v');
		assert.equal(await dialog.count(), 1);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Sauvegarder', exact: true }).click();
		await dialog.getByRole('radio', { name: 'Maintenant', exact: true }).waitFor();
		assert.equal(
			await dialog.getByRole('radio', { name: 'Maintenant', exact: true }).isChecked(),
			true
		);
		assert.equal(commands.filter((command) => command.path.endsWith('/template')).length, 0);
		await dialog.getByRole('button', { name: 'Revenir à l’édition', exact: true }).click();
		await page.getByRole('button', { name: 'Sauvegarder', exact: true }).click();
		await dialog.getByRole('button', { name: 'Enregistrer la version', exact: true }).click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).waitFor();
		const pattern = commands
			.findLast((command) => command.path.endsWith('/template'))
			.body.blocks.find((item) => item.title === 'Séance test');
		assert.equal(pattern.start_slot, 1);
		assert.equal(pattern.duration_slots, 3);
		assert.equal(pattern.weekday, 1);
		assert.equal(pattern.subject_id, null);
		assert.equal(pattern.teacher_id, null);
		assert.equal(pattern.room_id, null);
		const duplicate = commands
			.findLast((command) => command.path.endsWith('/template'))
			.body.blocks.find((item) => item.title === 'Copie test');
		assert.equal(duplicate.weekday, 2);
		assert.notEqual(duplicate.key, pattern.key);
		assert.equal(
			'effective_at' in
				commands.findLast((command) => command.path.endsWith('/template')).body,
			false
		);
		const savedRequests = commands.filter((command) =>
			command.path.endsWith('/template')
		).length;
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).click();
		await page.getByRole('button', { name: 'Quitter', exact: true }).click();
		await page
			.getByRole('status')
			.filter({ hasText: 'Aucun changement à enregistrer' })
			.waitFor();
		assert.equal(versions.length, 1);
		assert.equal(
			commands.filter((command) => command.path.endsWith('/template')).length,
			savedRequests
		);
		await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).click();
		for (const name of ['Matière', 'Enseignant ou khôlleur', 'Salle']) {
			assert.equal(
				await dialog
					.getByRole('group', { name, exact: true })
					.getByRole('radio', { checked: true })
					.count(),
				0
			);
		}
		for (const kind of ['Cours', 'TD', 'TP']) {
			await dialog.getByRole('radio', { name: kind, exact: true }).check();
			assert.equal(
				await dialog.getByRole('radio', { name: 'Khôlleur seul', exact: true }).count(),
				0
			);
			assert.equal(
				await dialog.getByRole('radio', { name: 'Zoé Maths', exact: true }).count(),
				1
			);
		}
		await dialog.getByRole('radio', { name: 'Khôlle', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Khôlleur seul', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Cours', exact: true }).check();
		assert.equal(
			await dialog
				.getByRole('group', { name: 'Enseignant ou khôlleur', exact: true })
				.getByRole('radio', { checked: true })
				.count(),
			0
		);
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		assert.equal(
			await dialog
				.getByRole('group', { name: 'Enseignant ou khôlleur', exact: true })
				.locator('.tag-choice.secondary')
				.count(),
			1
		);
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).click();
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.getByRole('alert').filter({ hasText: 'intitulé personnalisé' }).waitFor();
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).fill('Événement libre');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		const unassigned = commands.findLast((command) => command.path.endsWith('/series')).body
			.block;
		assert.equal(unassigned.subject_id, null);
		assert.equal(unassigned.teacher_id, null);
		assert.equal(unassigned.room_id, null);
		assert.equal(unassigned.title, 'Événement libre');
		await page.locator('.ec-event').first().click();
		assert.ok(await dialog.getByText(/Cette occurrence seulement sera modifiée/).isVisible());
		assert.equal(
			await dialog
				.getByRole('radio', { name: 'Celle-ci et les suivantes', exact: true })
				.count(),
			0
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.locator('.ec-event').first().hover();
		await page.keyboard.press('Control+c');
		const normalBounds = await page.locator('.ec-body .ec-day').nth(1).boundingBox();
		await page.mouse.click(
			normalBounds.x + normalBounds.width / 2,
			normalBounds.y + (5 * normalBounds.height) / 9 + 6,
			{ button: 'right' }
		);
		await page.getByRole('menuitem', { name: /Coller ici/ }).click();
		await dialog.waitFor();
		assert.equal(
			await dialog.getByLabel('Intitulé personnalisé', { exact: true }).inputValue(),
			block.title
		);
		assert.equal(
			await dialog.getByRole('radio', { name: 'Une seule fois', exact: true }).isChecked(),
			true
		);
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).fill('Copie ponctuelle');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		const punctual = commands.findLast((command) => command.path.endsWith('/series')).body
			.block;
		assert.equal(punctual.title, 'Copie ponctuelle');
		assert.equal(punctual.interval, 0);
		assert.equal(punctual.until, null);
		assert.equal(punctual.starts_on, '2026-09-08');
		const eventBox = await page.locator('.ec-event').first().boundingBox();
		const hourHeight =
			(await page.locator('.ec-body .ec-day').first().boundingBox()).height / 9;
		await page.mouse.move(eventBox.x + 20, eventBox.y + 12);
		await page.mouse.down();
		await page.mouse.move(eventBox.x + 20, eventBox.y + 12 + hourHeight, { steps: 12 });
		await page.mouse.up();
		await dialog.waitFor();
		assert.equal(await dialog.getByLabel('Début', { exact: true }).inputValue(), '08:55:00');
		const beforeMove = commands.length;
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.getByRole('heading', { name: 'Modifier cette occurrence ?' }).waitFor();
		assert.equal(commands.length, beforeMove);
		await dialog.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.setViewportSize({ width: 390, height: 844 });
		assert.ok(
			await page.getByRole('heading', { name: 'Première année', exact: true }).isVisible()
		);
		await page.getByRole('button', { name: 'Afficher les groupes', exact: true }).click();
		assert.ok(await page.getByLabel('Rechercher un élève', { exact: true }).isVisible());
		assert.ok(
			await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		);
		await page.setViewportSize({ width: 1440, height: 1000 });
		agendas[0].promotion_id = null;
		await page.goto(`${origin}/timetable`);
		await page.getByRole('alert').filter({ hasText: 'aucune promotion affectée' }).waitFor();
		await page.locator('button.agenda-open').first().click();
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		await dialog.locator('.critical-issue').waitFor();
		assert.equal(await page.locator('.warning-button.critical').count(), 1);
		assert.equal(await page.locator('.warning-button.clear').count(), 0);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).click();
		await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).click();
		await dialog.getByRole('radio', { name: 'TD', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Demis A / B', exact: true }).check();
		assert.equal(await dialog.getByRole('radio', { name: 'A', exact: true }).isChecked(), true);
		assert.equal(
			await dialog.getByRole('radio', { name: 'Groupes de khôlle', exact: true }).count(),
			0
		);
		await dialog.getByLabel('Longueur, en séances').fill('2');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		await dialog.getByText(/volumes inégaux/).waitFor();
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Heures par matière', exact: true }).click();
		await dialog.getByText('Afficher les données du graphique', { exact: true }).click();
		await dialog.getByRole('table').waitFor();
		assert.equal(
			await dialog
				.getByRole('row')
				.filter({ hasText: 'Mathématiques' })
				.getByRole('cell')
				.nth(1)
				.innerText(),
			'1 h'
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Sauvegarder', exact: true }).click();
		await dialog.getByRole('radio', { name: 'À une autre date', exact: true }).check();
		await dialog
			.getByLabel('Date et heure d’application', { exact: true })
			.fill('2026-09-08T15:00');
		await dialog.getByRole('button', { name: 'Enregistrer la version', exact: true }).click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).waitFor();
		assert.ok(
			commands.findLast((command) => command.path.endsWith('/template')).body.effective_at
		);
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).click();
		await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).click();
		await dialog.getByRole('radio', { name: 'Cours', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Demis A / B', exact: true }).check();
		await dialog.getByRole('radio', { name: 'B', exact: true }).check();
		await dialog.getByLabel('Longueur, en séances').fill('2');
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		assert.equal(await dialog.getByText(/volumes inégaux/).count(), 0);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Sauvegarder', exact: true }).click();
		await dialog.getByRole('radio', { name: 'À une autre date', exact: true }).check();
		await dialog
			.getByLabel('Date et heure d’application', { exact: true })
			.fill('2026-09-02T15:00');
		assert.equal(
			await dialog
				.getByRole('button', { name: 'Enregistrer la version', exact: true })
				.isDisabled(),
			true
		);
		await dialog
			.getByLabel('Je confirme le remplacement des séances passées.', { exact: true })
			.check();
		await dialog.getByRole('button', { name: 'Enregistrer la version', exact: true }).click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).waitFor();
		assert.equal(
			commands.findLast((command) => command.path.endsWith('/template')).body
				.acknowledge_history,
			true
		);
		await page
			.getByRole('button', { name: 'Éditer la semaine type', exact: true })
			.and(page.locator(':enabled'))
			.waitFor();
		agendas[0].promotion_id = 1;
		// Weekly resizes stay local until explicit version activation; dated exceptions require confirmation.
		const scheduledResizeAt = '2026-09-09T15:00:00Z';
		versions.at(-1).effective_at = scheduledResizeAt;
		versions.at(-1).effective_on = scheduledResizeAt.slice(0, 10);
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).click();
		const resizedKey = await page
			.locator('.ec-event')
			.first()
			.getAttribute('data-timetable-event-id');
		const initialPattern = structuredClone(
			patterns.find((item) => resizedKey.startsWith(item.key))
		);
		async function resizeBorder(
			edge,
			direction,
			path,
			expectedStatus = 200,
			templateKey = null,
			confirm = true
		) {
			const matching = templateKey
				? page.locator(`.ec-event[data-timetable-event-id^="${templateKey}-"]`)
				: page.locator('.ec-event').first();
			const target = edge === 'top' ? matching.first() : matching.last();
			const resizer = target.locator(
				edge === 'top' ? '.ec-resizer.ec-start' : '.ec-resizer:not(.ec-start)'
			);
			// Wait for the calendar's deferred event DOM rebuild before grabbing a handle.
			await page.evaluate(
				() =>
					new Promise((resolve) =>
						requestAnimationFrame(() => requestAnimationFrame(resolve))
					)
			);
			await resizer.waitFor();
			await resizer.scrollIntoViewIfNeeded();
			const handle = await resizer.boundingBox();
			const day = await page.locator('.ec-body .ec-day').first().boundingBox();
			const beforeCommands = commands.length;
			await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
			await page.mouse.down();
			await page.mouse.move(
				handle.x + handle.width / 2,
				handle.y + handle.height / 2 + (direction * (27.5 / 60) * day.height) / 9,
				{ steps: 12 }
			);
			await page.mouse.up();
			if (!path) {
				await page
					.getByRole('status')
					.filter({ hasText: 'Redimensionnement conservé' })
					.waitFor();
				assert.equal(commands.length, beforeCommands);
				assert.equal(await dialog.count(), 0);
				return;
			}
			await dialog
				.getByRole('heading', { name: 'Redimensionner cette occurrence ?' })
				.waitFor();
			assert.equal(commands.length, beforeCommands);
			assert.equal(
				await dialog.evaluate((element) => element.classList.contains('drawer')),
				false
			);
			const box = await dialog.boundingBox();
			assert.ok(Math.abs(box.x + box.width / 2 - (await page.viewportSize()).width / 2) < 2);
			if (!confirm) {
				await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
				assert.equal(commands.length, beforeCommands);
				return;
			}
			const saved = page.waitForResponse(
				(response) =>
					response.request().method() === 'POST' && response.url().includes(path)
			);
			await dialog.getByRole('button', { name: 'Confirmer', exact: true }).click();
			assert.equal((await saved).status(), expectedStatus);
			if (expectedStatus === 200)
				await page
					.getByRole('status')
					.filter({ hasText: 'Redimensionnement enregistré en préparation' })
					.waitFor();
			else {
				await dialog.getByRole('alert').filter({ hasText: 'L’agenda a changé' }).waitFor();
				await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
			}
			assert.equal(await dialog.count(), 0);
		}
		const beforeWeeklyResize = JSON.stringify(patterns);
		const beforeVersions = versions.length;
		await resizeBorder('top', 1, null, 200, initialPattern.key);
		await resizeBorder('bottom', -1, null, 200, initialPattern.key);
		assert.equal(JSON.stringify(patterns), beforeWeeklyResize);
		assert.equal(versions.length, beforeVersions);
		await page.getByRole('button', { name: 'Sauvegarder', exact: true }).click();
		await dialog.getByRole('radio', { name: 'À une autre date', exact: true }).check();
		await dialog
			.getByLabel('Date et heure d’application', { exact: true })
			.fill('2026-09-09T15:00');
		await dialog.getByRole('button', { name: 'Enregistrer la version', exact: true }).click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).waitFor();
		const resizedPattern = patterns.find((item) => item.key === initialPattern.key);
		assert.equal(resizedPattern.start_slot, initialPattern.start_slot + 1);
		assert.equal(resizedPattern.duration_slots, initialPattern.duration_slots - 2);
		const beforeDatedChanges = JSON.stringify(patterns);
		await page.getByRole('button', { name: 'Aujourd’hui', exact: true }).click();
		await resizeBorder('top', 1, '/timetable/command', 200, null, false);
		await resizeBorder('top', 1, '/timetable/command');
		const resizedOccurrence = commands.findLast((command) =>
			/\/series\//.test(command.path)
		).body;
		assert.equal(resizedOccurrence.scope, 'one');
		assert.equal(resizedOccurrence.block.start_slot, 1);
		assert.equal(resizedOccurrence.block.duration_slots, block.duration_slots - 1);
		await resizeBorder('bottom', -1, '/timetable/command');
		assert.equal(
			commands.findLast((command) => /\/series\//.test(command.path)).body.block
				.duration_slots,
			3
		);
		rejectResize = true;
		await resizeBorder('top', 1, '/timetable/command', 409);
		rejectResize = false;
		await page.locator('.ec-event').first().click();
		assert.equal(
			await dialog
				.getByRole('radio', { name: 'Celle-ci et les suivantes', exact: true })
				.count(),
			0
		);
		await dialog
			.getByLabel('Intitulé personnalisé', { exact: true })
			.fill('Exception confirmée');
		const beforeEdit = commands.length;
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.getByRole('heading', { name: 'Modifier cette occurrence ?' }).waitFor();
		assert.equal(commands.length, beforeEdit);
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(
			await dialog.getByLabel('Intitulé personnalisé', { exact: true }).inputValue(),
			'Exception confirmée'
		);
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		assert.equal(commands.at(-1).body.scope, 'one');
		assert.equal(commands.at(-1).body.block.title, 'Exception confirmée');
		await page.locator('.ec-event').first().click();
		const beforeDelete = commands.length;
		await dialog.getByRole('button', { name: 'Supprimer', exact: true }).click();
		await dialog.getByRole('heading', { name: 'Supprimer cette occurrence ?' }).waitFor();
		assert.equal(commands.length, beforeDelete);
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		await dialog.getByRole('button', { name: 'Supprimer', exact: true }).click();
		await dialog.getByRole('button', { name: 'Confirmer', exact: true }).click();
		await dialog.waitFor({ state: 'hidden' });
		assert.equal(commands.at(-1).body.scope, 'one');
		assert.equal(commands.at(-1).body.block, null);
		assert.equal(JSON.stringify(patterns), beforeDatedChanges);
		warningTemplate = {
			...patterns[0],
			key: 'd'.repeat(32),
			weekday: 1,
			interval: 1,
			phase: 1,
			start_slot: 0,
			duration_slots: 2,
			subject_id: 1,
			teacher_id: 2,
			room_id: 1,
			kind: 'tp',
			title: 'Séance repère',
			target_kind: 'promotion',
			target_number: null,
			target_user_id: null
		};
		patterns = [...patterns, warningTemplate];
		teachingUnavailable = true;
		await page.reload();
		await page.locator('.ec-event').first().waitFor();
		await page.getByLabel('Date affichée', { exact: true }).fill('2026-09-21');
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		const datedWarning = dialog
			.locator('.warning-event-link')
			.filter({ hasText: 'Séance individuelle' });
		await datedWarning.waitFor();
		assert.match(await datedWarning.innerText(), /lundi 7 septembre 2026 · 13:00–13:55/);
		assert.ok(await datedWarning.locator('..').locator('.role-kholleur').count());
		assert.equal(await datedWarning.locator('..').locator('.tag').innerText(), 'Khôlle');
		assert.ok(
			await datedWarning
				.locator('..')
				.locator('.role-name')
				.evaluate(
					(element) =>
						getComputedStyle(element).color !==
						getComputedStyle(element.parentElement).color
				)
		);
		await datedWarning.click();
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).waitFor();
		assert.equal(
			await page.getByLabel('Date affichée', { exact: true }).inputValue(),
			'2026-09-07'
		);
		assert.equal(await dialog.getByLabel('Date', { exact: true }).inputValue(), '2026-09-07');
		assert.equal(
			await dialog.getByRole('radio', { name: 'Khôlle', exact: true }).isChecked(),
			true
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		const weeklyWarning = dialog
			.locator('.warning-event-link')
			.filter({ hasText: 'Séance repère' });
		assert.match(await weeklyWarning.innerText(), /mardi · 08:00–08:55/);
		assert.doesNotMatch(await weeklyWarning.innerText(), /2026/);
		assert.ok(await weeklyWarning.locator('..').locator('.role-teacher').count());
		await weeklyWarning.click();
		await dialog.getByLabel('Intitulé personnalisé', { exact: true }).waitFor();
		assert.equal(
			await dialog.getByLabel('Intitulé personnalisé', { exact: true }).inputValue(),
			'Séance repère'
		);
		assert.equal(
			await dialog.getByRole('radio', { name: 'Mardi', exact: true }).isChecked(),
			true
		);
		assert.equal(
			await dialog.getByRole('radio', { name: 'TP', exact: true }).isChecked(),
			true
		);
		assert.equal(await page.getByLabel('Date affichée', { exact: true }).count(), 0);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Quitter', exact: true }).click();
		patterns = patterns.filter((item) => item.key !== warningTemplate.key);
		warningTemplate = null;
		teachingUnavailable = false;
		// Recheck external bookings at save time, including a booking added after opening the form.
		await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).click();
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Mme Test', exact: true }).check();
		await dialog.getByLabel('Date', { exact: true }).fill('2026-09-07');
		await dialog
			.getByLabel('Intitulé personnalisé', { exact: true })
			.fill('Intercalendriers ponctuelle');
		foreignBookings = true;
		const beforeConflict = commands.length;
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog
			.getByRole('heading', { name: 'Enseignant déjà occupé', exact: true })
			.waitFor();
		assert.equal(commands.length, beforeConflict);
		assert.match(
			await dialog.locator('.notification.is-danger').innerText(),
			/calendrier 2 \(Deuxième année\)/
		);
		assert.equal(
			await dialog.evaluate((element) => element.classList.contains('drawer')),
			false
		);
		await dialog.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(
			await dialog.getByLabel('Intitulé personnalisé', { exact: true }).inputValue(),
			'Intercalendriers ponctuelle'
		);
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog
			.getByRole('button', { name: 'Confirmer malgré le conflit', exact: true })
			.click();
		await dialog.waitFor({ state: 'hidden' });
		assert.equal(commands.at(-1).body.block.title, 'Intercalendriers ponctuelle');
		await page.locator('.warning-button.critical').waitFor();
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		assert.ok(
			await dialog.locator('.critical-issue').filter({ hasText: 'calendrier 2' }).count()
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).click();
		await page.getByRole('button', { name: 'Ajouter une séance', exact: true }).click();
		await dialog.getByRole('radio', { name: 'Mathématiques', exact: true }).check();
		await dialog.getByRole('radio', { name: 'Mme Test', exact: true }).check();
		await dialog
			.getByLabel('Intitulé personnalisé', { exact: true })
			.fill('Intercalendriers semaine');
		const beforeWeeklyConflict = commands.length;
		await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await dialog
			.getByRole('heading', { name: 'Enseignant déjà occupé', exact: true })
			.waitFor();
		assert.equal(commands.length, beforeWeeklyConflict);
		await dialog
			.getByRole('button', { name: 'Confirmer malgré le conflit', exact: true })
			.click();
		await dialog.waitFor({ state: 'hidden' });
		assert.equal(commands.length, beforeWeeklyConflict); // The weekly editing buffer remains local.
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		assert.ok(
			await dialog.locator('.critical-issue').filter({ hasText: 'calendrier 2' }).count()
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		await page.getByRole('button', { name: 'Sauvegarder', exact: true }).click();
		await dialog.getByRole('button', { name: 'Enregistrer la version', exact: true }).click();
		await dialog
			.getByRole('button', { name: 'Confirmer malgré le conflit', exact: true })
			.click();
		await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).waitFor();
		foreignBookings = false;
		pupilCollision = true;
		await page.reload();
		await page.locator('.warning-button.critical').waitFor();
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		assert.ok(
			await dialog.locator('.critical-issue').filter({ hasText: 'Les mêmes élèves' }).count()
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		pupilCollision = false;
		groupsDefined = false;
		teacherUnavailable = true;
		await Promise.all([
			page.waitForResponse((response) => response.url().includes('/timetable/data')),
			page.evaluate(() => window.dispatchEvent(new Event('focus')))
		]);
		await page.getByRole('button', { name: /Points à vérifier/ }).click();
		assert.equal(await dialog.locator('.critical-issue').count(), 0);
		await dialog
			.getByText(/n’est pas défini/)
			.first()
			.waitFor();
		await dialog.getByText(/Un enseignant indisponible reste affecté/).waitFor();
		assert.ok(await dialog.locator('.role-badge').filter({ hasText: 'Mme Test' }).count());
		assert.equal(
			await page.locator('.warning-button.critical, .warning-button.clear').count(),
			0
		);
		await dialog.getByRole('button', { name: 'Fermer la fenêtre' }).click();
		groupsDefined = true;
		teacherUnavailable = false;
		role = 'teacher';
		await page.goto(`${origin}/timetable/prof`);
		await page.locator('.ec-event').first().waitFor();
		assert.equal(
			await page
				.getByRole('button', { name: 'Éditer les disponibilités', exact: true })
				.count(),
			0
		);
		const deniedAvailability = await page.evaluate(
			async () =>
				(
					await fetch('/timetable/prof/data?school_year=2026&teacher_id=2', {
						method: 'POST',
						headers: { 'Content-Type': 'application/json' },
						body: JSON.stringify({ ranges: [] })
					})
				).status
		);
		assert.equal(deniedAvailability, 403);
		await page.goto(`${origin}/timetable/1`);
		await page.locator('.ec-event').first().waitFor();
		assert.equal(
			await page.getByRole('button', { name: 'Éditer la semaine type', exact: true }).count(),
			0
		);
		await page.locator('.ec-event').first().click({ button: 'right' });
		assert.equal(await page.getByRole('menu').count(), 0);
		await page.keyboard.press('Control+v');
		assert.equal(await dialog.count(), 0);
		role = 'pupil';
		assert.equal((await page.goto(`${origin}/timetable`)).status(), 403);
		assert.equal((await page.goto(`${origin}/timetable/1`)).status(), 403);
		assert.equal((await page.goto(`${origin}/timetable/prof`)).status(), 403);
		await page.goto(`${origin}/me`);
		const [generated] = await Promise.all([
			page.waitForResponse((response) => response.url() === `${origin}/me/calendar`),
			page.getByRole('button', { name: 'Générer mon lien', exact: true }).click()
		]);
		assert.equal(generated.status(), 200, await generated.text());
		const link = page.getByLabel('Votre lien personnel');
		await link.waitFor();
		assert.ok((await link.inputValue()).endsWith(`/calendar-feed/${'A'.repeat(43)}.ics`));
		await page.reload();
		assert.equal(await page.getByLabel('Votre lien personnel').count(), 0);
		assert.ok(
			await page.getByRole('button', { name: 'Régénérer mon lien', exact: true }).isVisible()
		);
		const response = await page.request.get(`${origin}/calendar-feed/${'A'.repeat(43)}.ics`);
		assert.equal(response.status(), 200);
		assert.equal(feedCookie, undefined);
		assert.deepEqual(errors, []);
	} finally {
		await browser?.close();
		const exited = once(child, 'exit');
		child.kill();
		await exited;
		await new Promise((resolve) => backend.close(resolve));
	}
});
