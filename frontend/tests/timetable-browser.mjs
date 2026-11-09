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
	let generationRun = null;
	let generationPolls = 0;
	let holdGenerationCompletion = false;
	let failNextGeneration = true;
	let observedGenerationRules;
	let releaseGroupAssignment, releaseGroupRefresh, signalGroupAssignment, signalGroupRefresh;
	const groupAssignmentStarted = new Promise((resolve) => (signalGroupAssignment = resolve));
	const groupRefreshStarted = new Promise((resolve) => (signalGroupRefresh = resolve));
	let holdGroupRefresh = false;
	let rejectNextGroupAssignment = false;
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
		rooms = [{ id: 1, name: 'B402', revision, kholle_capacity: 1 }];
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
	let kholleConfiguration = null;
	const wishesByYear = new Map();
	const workflowByYear = new Map();
	let rejectWishes = false;
	let holdWorkflowRefresh = false;
	let releaseWorkflowRefresh;
	let startWorkflowRefresh;
	const workflowRefreshStarted = new Promise((resolve) => {
		startWorkflowRefresh = resolve;
	});
	let pattern = null;
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
		if (/^\/api\/v1\/timetable\/kholloscope\/\d{4}\/workflow$/.test(url.pathname)) {
			if (request.method === 'GET' && holdWorkflowRefresh) {
				startWorkflowRefresh();
				await new Promise((resolve) => {
					releaseWorkflowRefresh = resolve;
				});
			}
			const year = Number(url.pathname.split('/')[5]);
			const stored = workflowByYear.get(year) ?? {
				validated: { volumes: false, wishes: false, service: false },
				selected_rooms: []
			};
			if (request.method === 'PUT') {
				let body = '';
				for await (const chunk of request) body += chunk;
				const data = JSON.parse(body);
				stored.validated[data.step] = true;
				if (data.step === 'service') stored.selected_rooms = data.rooms;
				if (data.step === 'service') stored.teacher_preferences = data.teacher_preferences;
				if (generationRun) generationRun.stale = true;
				workflowByYear.set(year, stored);
			}
			return reply({
				school_year: year,
				revision: 'a'.repeat(64),
				errors: kholleConfiguration ? [] : ['Configurer les khôlles.'],
				wish_errors: [],
				...stored,
				available: {
					volumes: true,
					wishes: stored.validated.volumes,
					service: stored.validated.wishes
				},
				review: { volumes: false, wishes: false, service: false },
				conflicts: { volumes: [], wishes: [], service: [] },
				needs: { 1: 161.25 },
				teacher_preferences: [
					{
						user_id: 2,
						prefer_own_promotion:
							stored.teacher_preferences?.[0]?.prefer_own_promotion ?? true,
						effective: true,
						promotion_ids: [1]
					},
					{
						user_id: 4,
						prefer_own_promotion:
							stored.teacher_preferences?.find((item) => item.user_id === 4)
								?.prefer_own_promotion ?? true,
						effective: true,
						promotion_ids: [1, 2, 3]
					}
				],
				rooms: [
					{ id: 1, name: 'C105', revision },
					{ id: 2, name: 'C106', revision }
				],
				subjects: [
					{
						...subjects[0],
						icon: 'book',
						staff: [
							{
								id: 2,
								name: 'Marie Test',
								first_name: 'Marie',
								last_name: 'Test',
								roles: ['teacher'],
								sessions: wishesByYear.get(year) ?? 0
							},
							{
								id: 4,
								name: 'Paul Kholleur',
								first_name: 'Paul',
								last_name: 'Kholleur',
								roles: ['kholleur'],
								sessions: 1
							},
							{
								id: 6,
								name: 'Enseignant Sans Service',
								first_name: 'Enseignant',
								last_name: 'Sans Service',
								roles: ['teacher'],
								sessions: 0
							}
						]
					}
				]
			});
		}
		if (/^\/api\/v1\/timetable\/kholloscope\/\d{4}\/wishes$/.test(url.pathname)) {
			const year = Number(url.pathname.split('/')[5]);
			if (request.method === 'PUT') {
				let body = '';
				for await (const chunk of request) body += chunk;
				if (rejectWishes) {
					rejectWishes = false;
					response.statusCode = 409;
					return reply({ detail: 'Les souhaits ont changé. Rechargez la page.' });
				}
				const entries = JSON.parse(body).entries;
				assert.equal(entries.find((entry) => entry.subject_id === 999).sessions, 4);
				wishesByYear.set(year, entries[0]?.sessions ?? null);
			}
			return reply({
				school_year: year,
				revision: 'a'.repeat(64),
				unassigned: [],
				subjects: [
					{
						...subjects[0],
						icon: 'book',
						staff: [
							{
								id: 2,
								name: 'Marie Test',
								first_name: 'Marie',
								last_name: 'Test',
								roles: ['teacher', 'kholleur'],
								sessions: wishesByYear.get(year) ?? null
							}
						]
					},
					{
						id: 999,
						name: 'Allemand',
						icon: 'book',
						color: '#449955',
						staff: [
							{
								id: 99,
								name: 'Paul Exemple',
								first_name: 'Paul',
								last_name: 'Exemple',
								roles: ['teacher'],
								sessions: 4
							}
						]
					}
				]
			});
		}
		if (
			/\/kholloscope\/(?!2027)\d{4}\/generation$/.test(url.pathname) &&
			request.method === 'GET'
		) {
			return reply({ source_revision: 'a'.repeat(64), ready: false, run: null });
		}
		if (
			/\/kholloscope\/2027\/generation(?:\/(?:session|cancel|save|apply|remove))?$/.test(
				url.pathname
			)
		) {
			let payload = {};
			if (request.method !== 'GET') {
				let raw = '';
				for await (const chunk of request) raw += chunk;
				payload = JSON.parse(raw);
			}
			if (request.method === 'POST' && url.pathname.endsWith('/generation')) {
				observedGenerationRules = payload.rules;
				generationRun = {
					id: revision,
					status: 'running',
					revision,
					stale: false,
					rules: payload.rules,
					logs: [
						...Array.from({ length: 80 }, (_, i) => `[00:00:000] Préparation ${i + 1}`),
						'[00:00:123] Recherche A/B en cours'
					],
					calendars: [
						{
							id: 1,
							calendar_id: 1,
							school_year: 2027,
							settings,
							slots,
							weeks: {},
							series: [],
							revision
						}
					],
					result: null
				};
				generationPolls = 0;
				return reply({ id: revision });
			}
			if (url.pathname.endsWith('/save')) {
				assert.equal(payload.expected_revision, generationRun.revision);
				generationRun.result.saved = true;
				return reply({ revision });
			}
			if (url.pathname.endsWith('/session')) {
				Object.assign(generationRun.result.sessions[0], {
					day: payload.day,
					start: payload.start,
					room_id: payload.room_id,
					locked: payload.locked
				});
				generationRun.result.mappings = [];
				generationRun.result.saved = false;
				return reply({ revision });
			}
			if (url.pathname.endsWith('/apply')) {
				assert.equal(payload.confirmed_live, true);
				generationRun.result.applied = true;
				return reply({ applied: true, revision });
			}
			if (url.pathname.endsWith('/remove')) {
				assert.equal(payload.confirmation, 'SUPPRIMER');
				assert.equal(payload.scope, 'future');
				generationRun.result.applied = false;
				generationRun.result.withdrawn = {
					scope: payload.scope,
					removed: 1,
					at: '2026-09-01'
				};
				return reply({ removed: 1, revision });
			}
			if (url.pathname.endsWith('/cancel')) {
				generationRun.status = 'cancelled';
				return reply({ cancelled: true });
			}
			if (
				generationRun?.status === 'running' &&
				++generationPolls >= 3 &&
				!holdGenerationCompletion
			) {
				if (failNextGeneration) {
					failNextGeneration = false;
					generationRun.status = 'failed';
					generationRun.logs.push('Calcul interrompu');
					return reply({
						source_revision: 'a'.repeat(64),
						ready: true,
						run: generationRun
					});
				}
				const seat = {
					id: 'seat1',
					calendar_id: 1,
					subject_id: 1,
					teacher_id: 2,
					room_id: 1,
					day: '2026-09-07',
					start: 57600,
					end: 60900,
					phase: 0
				};
				generationRun.status = 'completed';
				generationRun.logs.push('Terminé : affectez les groupes');
				generationRun.result = {
					sessions: [seat],
					template: [{ ...seat }],
					moved: 0,
					applied: false,
					mappings: [],
					reference: '2026-09-07',
					quotas: [
						{
							calendar_id: 1,
							subject_id: 1,
							sessions: 1,
							original_minutes: 60,
							rounded: false
						}
					]
				};
			}
			return reply({ source_revision: 'a'.repeat(64), ready: true, run: generationRun });
		}
		if (url.pathname === '/api/v1/timetable/kholloscope/2027/pdf') {
			response.setHeader('Content-Type', 'application/pdf');
			return response.end('%PDF-1.4\n%%EOF');
		}
		if (url.pathname === '/api/v1/timetable/kholloscope/2027/groups') {
			if (request.method === 'PUT') {
				let raw = '';
				for await (const chunk of request) raw += chunk;
				const input = JSON.parse(raw);
				assert.ok(['cycle', 'weekly'].includes(input.mode));
				if (rejectNextGroupAssignment) {
					rejectNextGroupAssignment = false;
					response.statusCode = 503;
					return reply({ detail: 'Affectation momentanément indisponible.' });
				}
				if (!releaseGroupAssignment) {
					signalGroupAssignment();
					await new Promise((resolve) => (releaseGroupAssignment = resolve));
					holdGroupRefresh = true;
				}
				generationRun.result.mappings = [{ calendar_id: 1, track: 1, group: 7 }];
				generationRun.result.assignment_mode = input.mode;
				return reply({ revision });
			}
			if (holdGroupRefresh) {
				holdGroupRefresh = false;
				signalGroupRefresh();
				await new Promise((resolve) => (releaseGroupRefresh = resolve));
			}
			return reply({
				revision,
				mappings: generationRun.result.mappings,
				assigned_sessions: generationRun.result.mappings.length
					? generationRun.result.sessions.map((s) => ({ ...s, group: 7 }))
					: [],
				schedule: generationRun.result.sessions.map((s) => ({ ...s, track: 1 })),
				calendars: [{ id: 1, name: agenda.name, groups: [7], tracks: 1 }]
			});
		}
		if (url.pathname === '/api/v1/timetable/kholloscope') {
			const errors = kholleConfiguration ? [] : ['Saisir les khôlles du calendrier 1.'];
			return reply({
				years: [2027, 2026],
				school_year: Number(url.searchParams.get('school_year') ?? 2027),
				errors,
				calendars: errors.length
					? []
					: [
							{
								id: 1,
								name: agenda.name,
								weeks: 2,
								group_count: 15,
								group_size: 3,
								settings: {
									...kholleConfiguration,
									subjects: kholleConfiguration.subjects.map((entry) => ({
										...entry,
										...subjects.find(
											(subject) => subject.id === entry.subject_id
										),
										icon: 'book'
									}))
								}
							}
						]
			});
		}
		if (url.pathname === '/api/v1/timetable/calendars/1/kholle/preview') {
			return reply({
				settings: kholleConfiguration,
				revision,
				year_revision: revision,
				group_count: 15,
				group_size: 3,
				weeks: [
					{ start: '2026-09-07', end: '2026-09-11', number: 1, days: 5, eligible: true },
					{ start: '2026-09-14', end: '2026-09-18', number: 2, days: 2, eligible: false },
					{ start: '2026-09-21', end: '2026-09-25', number: 3, days: 3, eligible: true }
				]
			});
		}
		if (url.pathname === '/api/v1/timetable/calendars/1/kholle') {
			let body = '';
			for await (const chunk of request) body += chunk;
			kholleConfiguration = JSON.parse(body).settings;
			return reply({ revision });
		}
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
					text_color: '#244BC1'
				}
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
						? [
								'users.manage',
								'users.read',
								'promotions.manage',
								'statistics.read',
								'kholloscope.read',
								'kholloscope.write'
							]
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
			if (url.pathname === '/api/v1/timetable/rooms') {
				const created = {
					id: rooms.length + 1,
					name: data.name,
					kholle_capacity: data.kholle_capacity,
					revision
				};
				rooms.push(created);
				return reply(created);
			}
			if (
				/^\/api\/v1\/timetable\/rooms\/\d+$/.test(url.pathname) &&
				request.method === 'PUT'
			) {
				const item = rooms.find(
					(room) => room.id === Number(url.pathname.split('/').at(-1))
				);
				const impacted =
					item.name === 'Salle multiple' && data.kholle_capacity < item.kholle_capacity;
				if (impacted && !data.confirmed_capacity_reduction) {
					return reply({
						confirmation_required: true,
						impact_revision: 'c'.repeat(64),
						message:
							'Cette diminution nécessitera une révision et un recalcul du kholloscope.'
					});
				}
				if (impacted) assert.equal(data.expected_impact_revision, 'c'.repeat(64));
				Object.assign(item, { name: data.name, kholle_capacity: data.kholle_capacity });
				return reply({ ...item, revision_required: impacted });
			}
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
		await page.goto(origin + '/dashboard?tab=overview');
		assert.equal(await page.locator('.workspace-greeting').count(), 0);
		assert.equal(
			await page
				.getByText('Tout votre établissement, en un regard.', { exact: true })
				.count(),
			0
		);
		assert.equal(await page.getByText('Pilotage de la plateforme', { exact: true }).count(), 0);
		const calendarAlerts = page.getByRole('region', { name: 'Alertes des calendriers' });
		const calendarLink = calendarAlerts
			.getByRole('link', { name: /Points à vérifier/ })
			.first();
		await calendarLink.waitFor();
		assert.match(await calendarLink.getAttribute('href'), /checks=1/);
		await calendarLink.click();
		await page.getByRole('dialog', { name: 'Points à vérifier', exact: true }).waitFor();
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Fermer la fenêtre', exact: true })
			.click();
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
		await page.getByRole('button', { name: 'Succès 2xx', exact: true }).waitFor();
		const monitor = page.locator('.api-monitoring');
		assert.equal(await monitor.getByRole('slider').count(), 0);
		assert.equal(await monitor.locator('.monitor-details').count(), 0);
		assert.equal(await monitor.getByRole('img').count(), 1);
		const latencyPlot = monitor.getByRole('img').first();
		assert.equal(await latencyPlot.getAttribute('viewBox'), '0 0 1100 220');
		assert.equal(await latencyPlot.locator('.request-bar').count(), 4);
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
		assert.equal(await latencyPlot.locator('.request-bar').count(), 4);
		for (const [label, key] of [
			['Succès 2xx', 'successes'],
			['Redirections 3xx', 'redirects'],
			['Refus et erreurs 4xx', 'client_errors'],
			['Erreurs serveur 5xx', 'server_errors']
		]) {
			const legend = monitor.getByRole('button', { name: label, exact: true });
			await legend.click();
			assert.equal(await legend.getAttribute('aria-pressed'), 'false');
			assert.equal(await latencyPlot.locator(`rect[data-series="${key}"]`).count(), 0);
			await legend.focus();
			await page.keyboard.press('Enter');
			assert.equal(await latencyPlot.locator(`rect[data-series="${key}"]`).count(), 1);
		}
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
		assert.equal(
			await monitor.getByRole('checkbox', { name: 'Afficher en pourcentage' }).count(),
			0
		);
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
		await page.getByRole('link', { name: 'Kholloscope', exact: true }).click();
		await page
			.getByRole('alert')
			.filter({ hasText: 'Saisir les khôlles du calendrier 1.' })
			.waitFor();
		assert.ok(page.url().endsWith('/timetable/kholloscope'));
		assert.equal(await page.getByLabel('Année scolaire', { exact: true }).inputValue(), '2027');
		await page.getByLabel('Année scolaire', { exact: true }).selectOption('2026');
		await page.waitForURL(/school_year=2026/);
		assert.equal(await page.getByLabel('Année scolaire', { exact: true }).inputValue(), '2026');
		await page.locator('.sidebar-title').click();
		assert.equal(await page.getByRole('button', { name: 'kholle', exact: true }).count(), 0);
		agenda.promotion_id = null;
		await page.goto(origin + '/timetable/kholloscope?school_year=2026&tab=volumes');
		await page.getByText('Affectez une promotion à cet agenda', { exact: false }).waitFor();
		assert.equal(await page.getByRole('region', { name: 'Volumes de khôlle' }).count(), 0);
		agenda.promotion_id = 1;
		await page.reload();
		const kholleDialog = page.getByRole('region', { name: 'Volumes de khôlle' });
		await kholleDialog
			.getByText('2 semaine(s) disponible(s) · 15 groupe(s) de khôlle.')
			.waitFor();
		await kholleDialog.getByRole('button', { name: 'Mathématiques', exact: true }).click();
		await kholleDialog
			.getByLabel('Heures par groupe · Mathématiques', { exact: true })
			.fill('21,5');
		assert.equal(
			await page.evaluate(() => {
				const event = new Event('beforeunload', { cancelable: true });
				window.dispatchEvent(event);
				return event.defaultPrevented;
			}),
			true
		);
		await kholleDialog
			.getByText('161,25 h de khôlle/semaine pour l’équipe pédagogique', { exact: true })
			.waitFor();
		await kholleDialog.locator('.pupil-average').filter({ hasText: '215,00' }).waitFor();
		await kholleDialog.getByLabel('Fin · vendredi soir').selectOption('2026-09-11');
		await kholleDialog
			.getByText('322,50 h de khôlle/semaine pour l’équipe pédagogique', { exact: true })
			.waitFor();
		await kholleDialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await page.locator('[aria-label="Volumes de khôlle"][aria-busy="false"]').waitFor();
		await kholleDialog
			.getByRole('img', { name: 'Mathématiques : 21h30', exact: true })
			.waitFor();
		await kholleDialog.getByText('Total annuel par groupe', { exact: false }).waitFor();
		assert.deepEqual(kholleConfiguration.subjects, [{ subject_id: 1, minutes: 1290 }]);
		await page.reload();
		await kholleDialog.getByRole('button', { name: 'Modifier', exact: true }).click();
		assert.equal(
			await kholleDialog
				.getByLabel('Heures par groupe · Mathématiques', { exact: true })
				.inputValue(),
			'21.5'
		);
		await kholleDialog
			.getByLabel('Heures par groupe · Mathématiques', { exact: true })
			.fill('22');
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer et continuer' }).isDisabled(),
			true
		);
		await kholleDialog
			.getByLabel('Heures par groupe · Mathématiques', { exact: true })
			.fill('21.5');
		const noChangeWrites = [];
		const trackVolumeWrite = (request) => {
			if (request.method() === 'POST' && request.url().includes('/timetable/command'))
				noChangeWrites.push(request);
		};
		page.on('request', trackVolumeWrite);
		await kholleDialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await kholleDialog.getByRole('button', { name: 'Modifier', exact: true }).waitFor();
		assert.equal(await kholleDialog.getByRole('textbox').count(), 0);
		assert.equal(noChangeWrites.length, 0);
		page.off('request', trackVolumeWrite);
		await page.locator('.sidebar-title').click();
		const toggle = page.getByRole('switch', { name: 'Diffuser aux élèves PTSI annuel' });
		await page.getByRole('link', { name: 'Kholloscope', exact: true }).click();
		await page.getByRole('heading', { name: 'Calendriers et volumes', exact: true }).waitFor();
		assert.equal(
			await page
				.getByRole('link', { name: /Souhaits de service/ })
				.getAttribute('aria-disabled'),
			'true'
		);
		holdWorkflowRefresh = true;
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await workflowRefreshStarted;
		await page.locator('.step.done').filter({ hasText: 'Calendriers et volumes' }).waitFor();
		await page.locator('.step.current').filter({ hasText: 'Souhaits de service' }).waitFor();
		assert.equal(
			await page
				.getByRole('link', { name: /Souhaits de service/ })
				.getAttribute('aria-disabled'),
			'false'
		);
		holdWorkflowRefresh = false;
		releaseWorkflowRefresh?.();
		await page.waitForURL(/tab=wishes/);
		await page.getByRole('spinbutton', { name: /Séances sur deux semaines/ }).waitFor();
		assert.equal(
			await page
				.locator('.wishes')
				.getByRole('button', { name: 'Modifier', exact: true })
				.count(),
			0
		);
		assert.equal(await page.locator('.wishes .subject-panel').count(), 1);
		assert.equal(
			await page.locator('.wishes').getByText('Allemand', { exact: true }).count(),
			0
		);
		assert.equal(
			await page.locator('.wishes').getByText('Paul Exemple', { exact: true }).count(),
			0
		);
		const wishInput = page.getByRole('spinbutton', { name: /Séances sur deux semaines/ });
		async function assertUntouchedSteps(labels) {
			for (const label of labels) {
				const step = page.locator('.step').filter({ hasText: label });
				assert.equal(await step.getAttribute('aria-disabled'), 'true');
				const classes = (await step.getAttribute('class')).split(/\s+/);
				assert.equal(classes.includes('current'), false, `${label} must not turn orange`);
				assert.equal(classes.includes('done'), false, `${label} was never validated`);
				assert.match(await step.innerText(), /Non faite/);
			}
		}
		const untouchedAfterWishes = [
			'Service et salles',
			'Génération du calendrier',
			'Affectation des groupes'
		];
		await assertUntouchedSteps(untouchedAfterWishes);
		await wishInput.fill('15.5');
		await assertUntouchedSteps(untouchedAfterWishes);
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer et continuer' }).isDisabled(),
			true
		);
		assert.equal(
			await page
				.locator('.wishes')
				.getByRole('button', { name: /^(Enregistrer|Annuler)$/ })
				.count(),
			0
		);
		await wishInput.fill('15');
		await assertUntouchedSteps(untouchedAfterWishes);
		rejectWishes = true;
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.getByRole('alert').filter({ hasText: 'Les souhaits ont changé.' }).waitFor();
		await assertUntouchedSteps(untouchedAfterWishes);
		assert.equal(await wishInput.inputValue(), '15');
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.waitForURL(/tab=service/);
		assert.equal(wishesByYear.get(2027), 15);
		await page.getByRole('link', { name: /Souhaits de service/ }).click();
		await page.waitForURL(/tab=wishes/);
		await page.reload();
		assert.equal(await page.getByRole('button', { name: 'Modifier', exact: true }).count(), 1);
		await page.getByRole('button', { name: 'Modifier', exact: true }).click();
		assert.equal(await wishInput.inputValue(), '15');
		if (process.env.KHOLLOSCOPE_SCREENSHOT) {
			await page.locator('.person-totals summary').click();
			await page
				.locator('.kholloscope-workspace')
				.screenshot({ path: process.env.KHOLLOSCOPE_SCREENSHOT });
		}
		assert.match(await page.locator('.subject-need').innerText(), /322,5 séances/);
		assert.match(await page.locator('.subject-gap').innerText(), /-307,5 \/ 2 semaines/);
		await page.locator('.person-totals').evaluate((element) => {
			element.open = true;
		});
		const recap = page.locator('.recap-table tbody tr');
		assert.equal(await recap.count(), 1);
		assert.match(await recap.innerText(), /Enseignant/);
		assert.match(await recap.innerText(), /Khôlleur/);
		assert.match(await recap.innerText(), /Mathématiques/);
		await page.setViewportSize({ width: 390, height: 844 });
		assert.equal(
			await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
			true
		);
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.waitForURL(/tab=service/);
		await page.locator('.step.done').filter({ hasText: 'Souhaits de service' }).waitFor();
		await page.locator('.step.current').filter({ hasText: 'Service et salles' }).waitFor();
		await page.getByRole('heading', { name: 'Service et salles', exact: true }).waitFor();
		assert.equal(
			await page
				.locator('.service-panel tbody tr')
				.filter({ hasText: 'Enseignant Sans Service' })
				.count(),
			0
		);
		assert.equal(
			await page.locator('.service-panel tbody tr').filter({ hasText: 'Marie Test' }).count(),
			1
		);
		await page.getByRole('checkbox', { name: 'C106' }).check();
		await page.getByRole('checkbox', { name: 'C105' }).check();
		await assertUntouchedSteps(['Génération du calendrier', 'Affectation des groupes']);
		const preferenceSwitch = page.getByRole('switch', {
			name: /Priorité à sa promotion — Marie Test/
		});
		const kholleurPreference = page.getByRole('switch', {
			name: /Priorité à ses promotions — Paul Kholleur/
		});
		assert.equal(await kholleurPreference.isEnabled(), true);
		assert.equal(await kholleurPreference.isChecked(), true);
		await page.getByText('Ses promotions en priorité', { exact: true }).waitFor();
		assert.equal(await page.getByText('Sans effet', { exact: false }).count(), 0);
		await kholleurPreference.uncheck();
		assert.equal(await preferenceSwitch.isChecked(), true);
		await preferenceSwitch.uncheck();
		await assertUntouchedSteps(['Génération du calendrier', 'Affectation des groupes']);
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.waitForURL(/tab=generation/);
		assert.deepEqual(workflowByYear.get(2027).selected_rooms, [
			{ subject_id: 1, room_ids: [1, 2] }
		]);
		assert.deepEqual(workflowByYear.get(2027).teacher_preferences, [
			{ user_id: 2, prefer_own_promotion: false },
			{ user_id: 4, prefer_own_promotion: false }
		]);
		await page.locator('.step.done').filter({ hasText: 'Service et salles' }).waitFor();
		await page.getByRole('link', { name: /Service et salles/ }).click();
		assert.equal(await page.getByRole('checkbox', { name: 'C106' }).isDisabled(), true);
		assert.equal(await preferenceSwitch.isDisabled(), true);
		await page
			.locator('.service-panel')
			.getByRole('button', { name: 'Modifier', exact: true })
			.waitFor();
		assert.equal(await page.locator('.step.done').count(), 3);
		await page
			.locator('.step.current')
			.filter({ hasText: 'Génération du calendrier' })
			.waitFor();
		const unloadPrevented = () =>
			page.evaluate(() => {
				const event = new Event('beforeunload', { cancelable: true });
				window.dispatchEvent(event);
				return event.defaultPrevented;
			});
		assert.equal(await unloadPrevented(), false);
		await page.reload();
		assert.equal(await page.getByRole('checkbox', { name: 'C106' }).isDisabled(), true);
		await page
			.locator('.service-panel')
			.getByRole('button', { name: 'Modifier', exact: true })
			.click();
		await page.getByRole('checkbox', { name: 'C106' }).uncheck();
		assert.equal(await preferenceSwitch.isChecked(), false);
		assert.equal(await kholleurPreference.isChecked(), false);
		await assertUntouchedSteps(['Génération du calendrier', 'Affectation des groupes']);
		assert.equal(await unloadPrevented(), true);
		await page.getByRole('checkbox', { name: 'C106' }).check();
		assert.equal(await unloadPrevented(), false);
		await page.getByRole('link', { name: /Génération du calendrier/ }).click();
		assert.equal(await page.getByLabel(/Équilibrer les engagements/).count(), 0);
		const durationInput = page.getByLabel('Temps maximal de calcul (minutes)');
		assert.equal(await durationInput.inputValue(), '15');
		for (const [minutes, valid] of [
			['0', false],
			['720', true],
			['721', false]
		]) {
			await durationInput.fill(minutes);
			assert.equal(await durationInput.evaluate((el) => el.checkValidity()), valid);
		}
		await durationInput.fill('15');
		await page.getByLabel('Conserver une pause déjeuner pour les intervenants').uncheck();
		holdGenerationCompletion = true;
		await page.getByRole('button', { name: 'Générer une proposition' }).click();
		const terminal = page.getByRole('log', { name: 'Journal du calcul' });
		await terminal.filter({ hasText: 'Recherche A/B en cours' }).waitFor();
		assert.equal(observedGenerationRules.time_limit, 900);
		const terminalAtBottom = () =>
			page.waitForFunction(() => {
				const log = document.querySelector('.solver-log');
				return (
					log &&
					log.scrollHeight > log.clientHeight &&
					log.scrollTop + log.clientHeight >= log.scrollHeight - 2
				);
			});
		await terminalAtBottom();
		await terminal.evaluate((element) => (element.scrollTop = 0));
		generationRun.logs.push('[00:01:234] Nouvelle ligne horodatée');
		await terminal.filter({ hasText: '[00:01:234] Nouvelle ligne horodatée' }).waitFor();
		await terminalAtBottom();
		holdGenerationCompletion = false;
		await page
			.getByRole('log', { name: 'Journal du calcul' })
			.filter({ hasText: 'Calcul interrompu' })
			.waitFor();
		const generationStep = page
			.locator('.step')
			.filter({ hasText: 'Génération du calendrier' });
		const groupStep = page.locator('.step').filter({ hasText: 'Affectation des groupes' });
		await page
			.locator('.step.current')
			.filter({ hasText: 'Génération du calendrier' })
			.waitFor();
		assert.equal(await groupStep.getAttribute('aria-disabled'), 'true');
		assert.ok(!(await groupStep.getAttribute('class')).includes('current'));
		await page.getByRole('link', { name: /Service et salles/ }).click();
		await page
			.locator('.service-panel')
			.getByRole('button', { name: 'Modifier', exact: true })
			.click();
		await page.getByRole('checkbox', { name: 'C106' }).uncheck();
		assert.equal(await generationStep.getAttribute('aria-disabled'), 'true');
		assert.equal(await groupStep.getAttribute('aria-disabled'), 'true');
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.waitForURL(/tab=generation/);
		await page.locator('.step.done').filter({ hasText: 'Service et salles' }).waitFor();
		await page
			.locator('.step.current')
			.filter({ hasText: 'Génération du calendrier' })
			.waitFor();
		assert.equal(await groupStep.getAttribute('aria-disabled'), 'true');
		assert.ok(!(await groupStep.getAttribute('class')).includes('current'));
		await page.goto(origin + '/timetable/kholloscope?school_year=2027&tab=groups');
		await page.getByRole('alert').filter({ hasText: 'Cette étape est verrouillée.' }).waitFor();
		await page.getByRole('link', { name: /Génération du calendrier/ }).click();
		assert.equal(
			await page.getByRole('checkbox', { name: /Continuer la recherche/ }).count(),
			0
		);
		await page.getByRole('button', { name: 'Générer une proposition' }).click();
		await page
			.getByRole('log', { name: 'Journal du calcul' })
			.filter({ hasText: 'Recherche A/B en cours' })
			.waitFor();
		await page
			.getByRole('log', { name: 'Journal du calcul' })
			.filter({ hasText: 'Terminé' })
			.waitFor();
		assert.equal(observedGenerationRules.teacher_lunch, false);
		assert.equal(observedGenerationRules.optimize, true);
		assert.equal(observedGenerationRules.preserve_locks, true);
		assert.equal('balance_odd_cycles' in observedGenerationRules, false);
		await page
			.locator('.step.current')
			.filter({ hasText: 'Génération du calendrier' })
			.waitFor();
		assert.equal(
			await page
				.locator('.step.current')
				.filter({ hasText: 'Génération du calendrier' })
				.count(),
			1
		);
		assert.equal(
			await page
				.getByRole('link', { name: /Affectation des groupes/ })
				.getAttribute('aria-disabled'),
			'true'
		);
		await page.reload();
		await page
			.locator('.step.current')
			.filter({ hasText: 'Génération du calendrier' })
			.waitFor();
		assert.equal(await groupStep.getAttribute('aria-disabled'), 'true');
		assert.equal(await page.getByRole('button', { name: 'Cycle A/B' }).count(), 0);
		const calendarPreview = page.getByRole('region', { name: 'Calendrier des propositions' });
		await page.setViewportSize({ width: 390, height: 844 });
		const weekControls = calendarPreview.locator('.week-navigation');
		const dateControl = await weekControls.getByLabel('Date affichée').boundingBox();
		const nextControl = await weekControls
			.getByRole('button', { name: 'Semaine suivante' })
			.boundingBox();
		assert.ok(dateControl.y + dateControl.height <= nextControl.y);
		assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
		await page.setViewportSize({ width: 1440, height: 1000 });
		assert.doesNotMatch(await calendarPreview.innerText(), /\p{L}\?\p{L}|\uFFFD/u);
		await calendarPreview
			.getByRole('heading', { name: 'Jours fériés et changements' })
			.waitFor();
		await calendarPreview.getByLabel('Intervenant', { exact: true }).selectOption('2');
		await calendarPreview.getByLabel('Matière', { exact: true }).selectOption('1');
		await calendarPreview.getByLabel('Salle', { exact: true }).selectOption('1');
		assert.equal(await calendarPreview.locator('.ec-event:not(.ec-bg-event)').count(), 1);
		await calendarPreview.getByRole('button', { name: 'Réinitialiser les filtres' }).click();
		assert.equal(
			await calendarPreview.getByLabel('Intervenant', { exact: true }).inputValue(),
			'0'
		);
		assert.equal(
			await calendarPreview
				.locator('.changes-panel')
				.getByRole('button', { name: 'Modifier' })
				.count(),
			0
		);
		const navBounds = await calendarPreview.locator('.week-navigation').boundingBox();
		const previewBounds = await calendarPreview.boundingBox();
		assert.ok(
			Math.abs(
				navBounds.x + navBounds.width / 2 - previewBounds.x - previewBounds.width / 2
			) < 2
		);

		await page.locator('.ec-event:not(.ec-bg-event)').first().click();
		await page
			.getByRole('dialog', { name: 'Modifier la séance' })
			.getByRole('button', { name: 'Enregistrer', exact: true })
			.click();
		await page.getByRole('dialog').waitFor({ state: 'detached' });
		assert.equal(generationRun.result.sessions[0].locked, true);
		assert.equal(
			await page.getByRole('link', { name: 'Affecter les groupes', exact: true }).count(),
			0
		);
		const timeShare = page.getByLabel('Répartition hebdomadaire (%)', { exact: true });
		const savedShare = await timeShare.inputValue();
		await timeShare.fill(String(Number(savedShare) + 1));
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer et continuer' }).isDisabled(),
			true
		);
		await timeShare.fill(savedShare);
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.waitForURL(/tab=groups/);
		assert.equal(generationRun.result.saved, true);
		await page.locator('.step.done').filter({ hasText: 'Génération du calendrier' }).waitFor();
		assert.equal(await page.locator('.changes-panel').count(), 0);
		assert.equal(await page.getByText(/séances annuelles/).count(), 0);
		assert.equal(await page.getByLabel('Rotation des groupes').inputValue(), 'cycle');
		await page.getByRole('button', { name: 'Affecter les groupes', exact: true }).click();
		await groupAssignmentStarted;
		const assigningButton = page.getByRole('button', {
			name: 'Affectation en cours…',
			exact: true
		});
		assert.equal(await assigningButton.isDisabled(), true);
		assert.equal(await assigningButton.getAttribute('aria-busy'), 'true');
		releaseGroupAssignment();
		await groupRefreshStarted;
		assert.equal(await assigningButton.isDisabled(), true);
		releaseGroupRefresh();
		await page
			.getByRole('status')
			.filter({
				hasText: 'Groupes affectés au brouillon. Vérifiez le calendrier avant de publier.'
			})
			.waitFor();
		const assignmentReview = page.getByRole('region', { name: 'Tableaux des affectations' });
		assert.equal(
			await page
				.getByRole('button', { name: 'Affecter les groupes', exact: true })
				.isEnabled(),
			false
		);
		assert.equal(await page.getByRole('button', { name: 'Affectation en cours…' }).count(), 0);
		await page.getByLabel('Rotation des groupes').selectOption('weekly');
		rejectNextGroupAssignment = true;
		await page.getByRole('button', { name: 'Affecter les groupes', exact: true }).click();
		await page
			.getByRole('alert')
			.filter({ hasText: 'Affectation momentanément indisponible.' })
			.waitFor();
		assert.equal(
			await page
				.getByRole('button', { name: 'Affecter les groupes', exact: true })
				.isEnabled(),
			true
		);
		await page.getByRole('button', { name: 'Affecter les groupes', exact: true }).click();
		await page
			.getByRole('status')
			.filter({ hasText: 'Groupes affectés au brouillon.' })
			.waitFor();
		await page.getByRole('link', { name: 'Télécharger le kholloscope PDF' }).waitFor();
		const pdf = await page.request.get(origin + '/timetable/kholloscope/pdf?school_year=2027');
		assert.equal(pdf.status(), 200);
		assert.equal(pdf.headers()['content-type'], 'application/pdf');
		assert.match(pdf.headers()['content-disposition'], /attachment/);
		assert.equal(pdf.headers()['cache-control'], 'private, no-store');
		assert.equal(
			(
				await page.request.get(origin + '/timetable/kholloscope/pdf?school_year=invalid')
			).status(),
			422
		);
		await assignmentReview.locator('.assignment-section > summary').click();
		await assignmentReview.locator('.assignment-subject > summary').click();
		assert.doesNotMatch(
			await page.locator('.generation-panel').innerText(),
			/\p{L}\?\p{L}|\uFFFD/u
		);
		await assignmentReview.getByRole('button', { name: /Groupe 7/ }).click();
		const assignmentDialog = page.getByRole('dialog', { name: 'Khôlle du groupe 7' });
		assert.ok((await assignmentDialog.innerText()).includes('Mme Test'));
		await assignmentDialog.getByRole('button', { name: 'Fermer' }).click();
		await page.getByRole('button', { name: 'Publier dans les agendas' }).click();
		await page
			.getByRole('dialog', { name: 'Appliquer le kholloscope' })
			.getByRole('button', { name: 'Confirmer', exact: true })
			.click();
		await page
			.getByRole('status')
			.filter({ hasText: 'Ce kholloscope est publié dans les agendas' })
			.waitFor();
		assert.deepEqual(generationRun.result.mappings, [{ calendar_id: 1, track: 1, group: 7 }]);
		assert.equal(
			await page
				.getByRole('button', { name: 'Retirer le kholloscope des agendas' })
				.isDisabled(),
			false
		);
		assert.equal(
			await page
				.getByRole('button', { name: 'Affecter les groupes', exact: true })
				.isDisabled(),
			true
		);
		const revisionStep = page.locator('.step').filter({ hasText: 'Révision' });
		assert.equal(await revisionStep.getAttribute('aria-disabled'), 'false');
		assert.match(await revisionStep.getAttribute('href'), /tab=revision/);
		await page.getByRole('link', { name: /Souhaits de service/ }).click();
		await page.getByRole('heading', { name: 'Souhaits de service', exact: true }).waitFor();
		assert.equal(await page.getByRole('button', { name: 'Modifier', exact: true }).count(), 0);
		assert.equal(
			await page.getByRole('button', { name: 'Enregistrer et continuer' }).count(),
			0
		);
		await page.getByRole('link', { name: /Affectation des groupes/ }).click();
		await page.getByRole('button', { name: 'Retirer le kholloscope des agendas' }).click();
		const withdrawal = page.getByRole('dialog', {
			name: 'Retirer le kholloscope',
			exact: true
		});
		await withdrawal.getByRole('button', { name: 'Annuler', exact: true }).click();
		assert.equal(generationRun.result.applied, true);
		await page.getByRole('button', { name: 'Retirer le kholloscope des agendas' }).click();
		await withdrawal.getByRole('button', { name: 'Continuer', exact: true }).click();
		const removal = page.getByRole('dialog', { name: 'Confirmer la suppression des khôlles' });
		assert.equal(
			await removal.getByRole('button', { name: 'Supprimer les khôlles' }).isDisabled(),
			true
		);
		await removal.getByLabel('Saisissez SUPPRIMER').fill('SUPPRIMER');
		await removal.getByRole('button', { name: 'Supprimer les khôlles' }).click();
		await removal.waitFor({ state: 'detached' });
		assert.equal(generationRun.result.applied, false);
		await page.getByRole('link', { name: /Souhaits de service/ }).click();
		await page.waitForURL(/tab=wishes/);
		await page.getByRole('heading', { name: 'Souhaits de service', exact: true }).waitFor();
		await page.getByRole('combobox', { name: 'Année scolaire' }).selectOption('2026');
		await page.waitForURL(/school_year=2026/);
		await page.getByRole('alert').filter({ hasText: 'Cette étape est verrouillée.' }).waitFor();
		await page.getByRole('link', { name: /Calendriers et volumes/ }).click();
		await page.getByRole('button', { name: 'Enregistrer et continuer' }).click();
		await page.waitForURL(/tab=wishes/);
		await wishInput.waitFor();
		assert.equal(await wishInput.inputValue(), '');
		await page.locator('.sidebar-title').click();
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
		const pdfExport = page.getByRole('link', { name: 'Exporter cette vue en PDF' });
		await pdfExport.waitFor();
		assert.equal(await pdfExport.getAttribute('target'), '_blank');
		const exportUrl = new URL(await pdfExport.getAttribute('href'), origin);
		assert.equal(exportUrl.pathname, '/timetable/1/pdf');
		assert.equal(exportUrl.searchParams.get('year_id'), '1');
		assert.equal(exportUrl.searchParams.get('node'), 'promotion');
		assert.equal(
			exportUrl.searchParams.get('day'),
			await page.getByLabel('Date affichée').inputValue()
		);
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
				// Statistics now derive from the selected audience's actual events, not canned board totals.
				assert.equal(rows.length, 1);
				for (const row of rows) {
					assert.ok(Math.abs(row.trackLeft - rows[0].trackLeft) < 1);
					assert.ok(Math.abs(row.trackWidth - rows[0].trackWidth) < 1);
					assert.ok(Math.abs(row.valueLeft - rows[0].valueLeft) < 1);
					assert.ok(row.labelLeft < row.labelRight && row.labelRight < row.trackLeft);
					assert.ok(row.trackWidth >= 40 && row.right <= width);
				}
				assert.ok(Number.parseFloat(rows[0].text.replace(',', '.')) > 0);
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
		await page.waitForFunction(
			() => document.querySelector('select[aria-label="Année scolaire"]')?.value === '2026'
		);
		assert.equal(
			await page.getByRole('combobox', { name: 'Année scolaire' }).inputValue(),
			'2026'
		);
		const teacherHourEvents = [
			{
				...board().events[0],
				id: 'teacher-week',
				kind: 'course',
				subject_id: 1,
				calendar_label: 'PT',
				session_minutes: 55,
				start: '2026-09-07T08:00:00+02:00',
				end: '2026-09-07T08:55:00+02:00'
			},
			{
				...board().events[0],
				id: 'teacher-later',
				kind: 'kholle',
				subject_id: 1,
				calendar_id: 2,
				calendar_label: 'PTSI',
				session_minutes: 55,
				start: '2026-09-14T08:00:00+02:00',
				end: '2026-09-14T08:27:30+02:00'
			}
		];
		await page.route('**/timetable/prof/data?**', (route) =>
			route.fulfill({
				json: {
					events: teacherHourEvents,
					availability: [
						{
							teacher_id: 2,
							revision: null,
							default: true,
							ranges: Array.from({ length: 6 }, (_, weekday) => ({
								weekday,
								start: 28800,
								end: weekday === 5 ? 43200 : 68400
							}))
						}
					]
				}
			})
		);
		await page.getByRole('button', { name: 'Actualiser', exact: true }).click();
		await page.getByRole('button', { name: 'Heures', exact: true }).click();
		const teacherHours = page.getByRole('dialog', {
			name: 'Heures des enseignants',
			exact: true
		});
		await teacherHours.waitFor();
		assert.equal(await teacherHours.locator('.hours-total strong').textContent(), '1 h');
		await teacherHours.getByRole('button', { name: 'Total sur l’année', exact: true }).click();
		assert.equal(await teacherHours.locator('.hours-total strong').textContent(), '1,5 h');
		await teacherHours.getByRole('button', { name: 'Par calendrier', exact: true }).click();
		assert.equal(await teacherHours.locator('.bar-row').count(), 2);
		const courseToggle = teacherHours.getByRole('button', { name: 'Cours', exact: true });
		await courseToggle.click();
		assert.equal(await courseToggle.getAttribute('aria-pressed'), 'false');
		assert.equal(await teacherHours.locator('.hours-total strong').textContent(), '1,5 h');
		await teacherHours.getByText('Afficher les données du graphique', { exact: true }).click();
		assert.equal(
			await teacherHours.getByRole('columnheader', { name: 'Khôlle', exact: true }).count(),
			1
		);
		for (const width of [1440, 390]) {
			await page.setViewportSize({ width, height: 1000 });
			assert.ok(await teacherHours.evaluate((el) => el.scrollWidth <= el.clientWidth));
		}
		await teacherHours.getByRole('button', { name: 'Fermer la fenêtre', exact: true }).click();
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.unroute('**/timetable/prof/data?**');
		await page.getByRole('button', { name: 'Actualiser', exact: true }).click();
		await page.getByRole('button', { name: 'Disponibilités', exact: true }).click();
		await page.locator('.ec-event:not(.ec-bg-event)').first().waitFor();
		assert.equal(await page.locator('.ec-body .ec-day').count(), 6);
		pattern = [];
		await page.getByRole('combobox', { name: 'Année scolaire' }).selectOption('2027');
		await page
			.getByRole('button', { name: 'Éditer les disponibilités', exact: true })
			.waitFor();
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
		await page.goto(origin + '/timetable/settings');
		for (const width of [1440, 390]) {
			await page.setViewportSize({ width, height: 1000 });
			const inputBox = await page.getByLabel('Année de rentrée').boundingBox();
			const buttonBox = await page
				.getByRole('button', { name: /^Créer \d{4}/ })
				.boundingBox();
			assert.ok(Math.abs(inputBox.height - buttonBox.height) < 1);
			assert.ok(Math.abs(inputBox.y - buttonBox.y) < 1);
		}
		await page.setViewportSize({ width: 1440, height: 1000 });
		await page.getByRole('button', { name: 'Salles', exact: true }).click();
		await page.getByRole('button', { name: 'Ajouter une salle' }).click();
		await page.getByLabel('Nom de la salle', { exact: true }).fill('Salle multiple');
		await page.getByLabel('Khôlles simultanées autorisées').fill('3');
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		const roomRow = page.locator('.room-row').filter({ hasText: 'Salle multiple' });
		await roomRow.getByText('3 khôlle(s) simultanée(s)').waitFor();
		await roomRow.getByRole('button', { name: 'Modifier', exact: true }).click();
		assert.equal(await page.getByLabel('Khôlles simultanées autorisées').inputValue(), '3');
		await page.getByLabel('Khôlles simultanées autorisées').fill('2');
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await page
			.getByRole('alert')
			.filter({ hasText: 'nécessitera une révision et un recalcul' })
			.waitFor();
		assert.equal(rooms.find((item) => item.name === 'Salle multiple').kholle_capacity, 3);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Annuler', exact: true })
			.click();
		assert.equal(await page.getByLabel('Khôlles simultanées autorisées').inputValue(), '2');
		assert.equal(rooms.find((item) => item.name === 'Salle multiple').kholle_capacity, 3);
		await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
		await page.getByRole('button', { name: 'Confirmer la diminution' }).click();
		await roomRow.getByText('2 khôlle(s) simultanée(s)').waitFor();
		await page
			.getByRole('status')
			.filter({ hasText: 'nécessitent une révision et un recalcul' })
			.waitFor();
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
		holdWorkflowRefresh = false;
		releaseWorkflowRefresh?.();
		await browser?.close();
		const exited = once(child, 'exit');
		child.kill();
		await exited;
		await new Promise((resolve) => backend.close(resolve));
	}
});
