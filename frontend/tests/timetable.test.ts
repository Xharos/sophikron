import assert from 'node:assert/strict';
import test from 'node:test';
import {
	clockSeconds,
	compareTimetableDisplayEvents,
	currentSchoolYear,
	preferredSchoolYear,
	defaultTimetableSettings,
	timetableDayBalance,
	isoWeek,
	mondayOf,
	shiftTimetableDate,
	timetableClock,
	timetableBackgrounds,
	timetableHolidayLabel,
	timetableTree,
	nodeReceives,
	selectedTimetableHours,
	teachingHours,
	nearestTimetableSlot,
	resizedTimetableSlots,
	orderedTimetableTeachers,
	teacherSubjectGradient,
	timetableAudienceLabel,
	timetableConflictDetails,
	type TimetableMember,
	type TimetableGroup,
	type TimetableEvent
} from '../src/lib/timetable.ts';

for (const family of ['halves', 'thirds', 'kholles'] as const)
	test('annual hours follow ' + family + ' and include common lessons', () => {
		const members = [1, 2, 3].map((id) => ({
			id,
			name: String(id),
			roles: ['user'],
			promotion_ids: [1],
			assignments: [{ promotion_id: 1, kind: family, number: id === 3 ? 2 : 1 }]
		}));
		const groups: TimetableGroup[] = [
			{ promotion_id: 1, kind: family, number: 1, student_ids: [1, 2] },
			{ promotion_id: 1, kind: family, number: 2, student_ids: [3] }
		];
		const root = timetableTree('PT', 1, members, groups);
		const year = {
			id: 1,
			calendar_id: 1,
			school_year: 2026,
			revision: null,
			settings: defaultTimetableSettings(2026),
			slots: [],
			series: [],
			weeks: { '2026-11-02': 1, '2026-11-09': 2 }
		};
		const events = [
			conflictEvent({
				year_id: 1,
				promotion_id: 1,
				target_kind: 'promotion',
				subject_id: 1,
				start: '2026-11-02T08:00:00+01:00',
				end: '2026-11-02T08:55:00+01:00'
			}),
			conflictEvent({
				year_id: 1,
				promotion_id: 1,
				target_kind: family,
				target_number: 1,
				subject_id: 1,
				kind: 'td',
				start: '2026-11-02T09:00:00+01:00',
				end: '2026-11-02T09:55:00+01:00'
			})
		];
		const board = { years: [year], events, members, groups, warnings: [] };
		const a = root.children.find((n) => n.kind === family && n.number === 1)!;
		const b = root.children.find((n) => n.kind === family && n.number === 2)!;
		assert.equal(selectedTimetableHours(board, year, a)[0].total, 2);
		assert.equal(selectedTimetableHours(board, year, a)[0].weekly.total, 1);
		assert.equal(selectedTimetableHours(board, year, b)[0].total, 1);
		assert.equal(selectedTimetableHours(board, year, root)[0].total, 1 + 2 / 3);
	});

test('odd PT cycles give a group 12 or 13 sessions, while even PTSI cycles give 15', () => {
	const members = [1, 2].map((id) => ({
		id,
		name: String(id),
		roles: ['user'],
		promotion_ids: [1],
		assignments: [{ promotion_id: 1, kind: 'kholles', number: id }]
	}));
	const groups: TimetableGroup[] = [1, 2].map((number) => ({
		promotion_id: 1,
		kind: 'kholles',
		number,
		student_ids: [number]
	}));
	const root = timetableTree('PT', 1, members, groups);
	const year = {
		id: 1,
		calendar_id: 1,
		school_year: 2026,
		revision: null,
		settings: defaultTimetableSettings(2026),
		slots: [],
		series: [],
		weeks: { '2026-09-07': 1 }
	};
	for (const counts of [
		[13, 12],
		[15, 15]
	]) {
		const events = counts.flatMap((count, group) =>
			Array.from({ length: count }, (_, index) => {
				const day = new Date(Date.UTC(2026, 8, 7 + 14 * index)).toISOString().slice(0, 10);
				return conflictEvent({
					id: group + '-' + index,
					kind: 'kholle',
					target_kind: 'kholles',
					target_number: group + 1,
					start: day + 'T08:00:00+02:00',
					end: day + 'T08:55:00+02:00'
				});
			})
		);
		const board = { years: [year], events, members, groups, warnings: [] };
		assert.equal(selectedTimetableHours(board, year, root.children[0])[0].kholle, counts[0]);
		assert.equal(selectedTimetableHours(board, year, root.children[1])[0].kholle, counts[1]);
		assert.equal(selectedTimetableHours(board, year, root)[0].kholle, (counts[0] + counts[1]) / 2);
	}
});

test('simultaneous blocks retain subject and teacher order across weeks and database order', () => {
	const blocks = [
		conflictEvent({ id: '1', title: 'Physique', teacher: 'Albert' }),
		conflictEvent({ id: '2', title: 'Mathématiques', teacher: 'Zoé' }),
		conflictEvent({ id: '3', title: 'Mathématiques', teacher: 'Émile' })
	];
	const labels = (events: TimetableEvent[]): string[] =>
		events
			.toSorted(compareTimetableDisplayEvents)
			.map((event) => `${event.title}/${event.teacher}`);
	assert.deepEqual(labels(blocks), ['Mathématiques/Émile', 'Mathématiques/Zoé', 'Physique/Albert']);
	const nextWeek = blocks.toReversed().map((event, index) => ({
		...event,
		id: `new-${index}`,
		series_id: `new-${index}`,
		start: event.start.replace('2026-09-07', '2026-09-14'),
		end: event.end.replace('2026-09-07', '2026-09-14')
	}));
	assert.deepEqual(labels(nextWeek), labels(blocks));
});

test('calendar ordering uses the first assigned teacher then room and numeric group', () => {
	const base = conflictEvent({ title: 'Mathématiques', teacher: 'Combined display' });
	const alpha = {
		...base,
		teacher_ids: [7, 8],
		teachers: [
			{ id: 8, name: 'Zoé', available: true },
			{ id: 7, name: 'Alice', available: true }
		]
	};
	assert.ok(compareTimetableDisplayEvents(alpha, { ...base, teacher: 'Bernard' }) < 0);
	assert.ok(compareTimetableDisplayEvents({ ...base, room: 'B2' }, { ...base, room: 'B10' }) < 0);
	assert.ok(
		compareTimetableDisplayEvents({ ...base, target_number: 2 }, { ...base, target_number: 10 }) < 0
	);
	assert.ok(
		compareTimetableDisplayEvents({ ...base, series_id: 'a' }, { ...base, series_id: 'b' }) < 0
	);
	assert.equal(compareTimetableDisplayEvents(base, base), 0);
});

test('calendar display preserves chronology even when subject names sort differently', () => {
	const early = conflictEvent({ start: '2026-09-07T08:00:00', title: 'Physique' });
	const late = conflictEvent({ start: '2026-09-07T09:00:00', title: 'Anglais' });
	assert.ok(compareTimetableDisplayEvents(early, late) < 0);
});

test('local specialists precede external specialists and retain all selectable teachers', () => {
	const teachers = [
		{ id: 1, name: 'A', subject_ids: [1], promotion_ids: [20] },
		{ id: 2, name: 'Z', subject_ids: [1, 2], promotion_ids: [10] },
		{ id: 3, name: 'B', subject_ids: [2] }
	];
	assert.deepEqual(
		orderedTimetableTeachers(teachers, 1, undefined, 10).map((t) => t.id),
		[2, 1, 3]
	);
	assert.deepEqual(
		orderedTimetableTeachers(teachers, 1).map((t) => t.id),
		[1, 2, 3]
	);
	const subjects = [
		{ id: 1, name: 'Maths', color: '#123456' },
		{ id: 2, name: 'TIPE', color: '#abcdef' }
	];
	assert.equal(
		teacherSubjectGradient(teachers[1], subjects),
		'linear-gradient(120deg, #123456, #abcdef)'
	);
	assert.equal(
		teacherSubjectGradient(teachers[0], subjects),
		'linear-gradient(120deg, #123456, #123456)'
	);
});

test('session text identifies whole classes, half groups, thirds and kholle groups', () => {
	assert.equal(timetableAudienceLabel({}), 'Classe entière');
	assert.equal(
		timetableAudienceLabel({ target_kind: 'halves', target_number: 2 }),
		'Demi-groupe B'
	);
	assert.equal(
		timetableAudienceLabel({ target_kind: 'thirds', target_number: 1 }),
		'Tiers de groupe X'
	);
	assert.equal(
		timetableAudienceLabel({ target_kind: 'kholles', target_number: 12 }),
		'Groupe de khôlle 012'
	);
	assert.equal(timetableAudienceLabel({ target_kind: 'student' }), 'Séance individuelle');
	assert.equal(timetableAudienceLabel({ audience_label: 'Demi-groupe A' }), 'Demi-groupe A');
});

test('holidays include both boundary dates and retain entered labels', () => {
	const settings = {
		...defaultTimetableSettings(2026),
		holidays: [{ name: 'Toussaint', start: '2026-10-17', end: '2026-11-01' }]
	};
	assert.equal(timetableHolidayLabel(settings, '2026-10-16'), null);
	assert.equal(timetableHolidayLabel(settings, '2026-10-17'), 'Vacances · Toussaint');
	assert.equal(timetableHolidayLabel(settings, '2026-11-01'), 'Vacances · Toussaint');
	assert.equal(timetableHolidayLabel(settings, '2026-11-02'), null);
	assert.equal(timetableHolidayLabel({ ...settings, end: '2026-10-18' }, '2026-10-19'), null);
});

test('holiday backgrounds cover the whole grid day and replace pauses and self', () => {
	const settings = {
		...defaultTimetableSettings(2026),
		holidays: [{ name: 'Ascension', start: '2027-05-06', end: '2027-05-07' }]
	};
	const backgrounds = timetableBackgrounds(settings, '2027-05-05');
	for (const day of ['2027-05-06', '2027-05-07']) {
		const items = backgrounds.filter((item) => item.start.startsWith(day));
		assert.equal(items.length, 1);
		assert.equal(items[0].title, 'Vacances · Ascension');
		assert.equal(items[0].start, `${day}T08:00:00`);
		assert.equal(items[0].end, `${day}T19:00:00`);
		assert.equal(items[0].display, 'background');
		assert.equal(items[0].editable, false);
		assert.deepEqual(items[0].classNames, ['timetable-holiday']);
	}
	assert.deepEqual(
		backgrounds.filter((item) => item.start.startsWith('2027-05-05')).map((item) => item.title),
		['Pause', 'Pause', 'Self ouvert · cours autorisés']
	);
});

test('full vacation weeks render one background per visible day including optional Saturday', () => {
	const settings = {
		...defaultTimetableSettings(2026),
		holidays: [{ name: 'Toussaint', start: '2026-10-17', end: '2026-11-01' }]
	};
	assert.equal(timetableBackgrounds(settings, '2026-10-21').length, 5);
	const saturday = timetableBackgrounds({ ...settings, saturday: true }, '2026-10-21');
	assert.equal(saturday.length, 6);
	assert.equal(saturday[5].start, '2026-10-24T08:00:00');
	assert.ok(saturday.every((item) => item.title === 'Vacances · Toussaint'));
	assert.ok(
		timetableBackgrounds(settings, '2026-11-02').every((item) => !item.id.startsWith('holiday-'))
	);
});

test('undated weekly patterns retain recess without painting dated holidays or self', () => {
	const settings = {
		...defaultTimetableSettings(2026),
		holidays: [{ name: 'Toussaint', start: '2026-10-17', end: '2026-11-01' }]
	};
	const backgrounds = timetableBackgrounds(settings, '2026-10-21', { dateless: true });
	assert.equal(backgrounds.length, 10);
	assert.ok(backgrounds.every((item) => item.title === 'Pause'));
	assert.ok(
		timetableBackgrounds(settings, '2026-11-02', { showLunch: false }).every(
			(item) => !item.id.startsWith('self-')
		)
	);
});

test('overlapping holiday periods share a single daily background with all labels', () => {
	const settings = {
		...defaultTimetableSettings(2026),
		holidays: [
			{ name: 'Toussaint', start: '2026-10-17', end: '2026-11-01' },
			{ name: 'Fermeture', start: '2026-10-21', end: '2026-10-21' }
		]
	};
	const day = timetableBackgrounds(settings, '2026-10-21').filter((item) =>
		item.start.startsWith('2026-10-21')
	);
	assert.equal(day.length, 1);
	assert.equal(day[0].title, 'Vacances · Toussaint · Fermeture');
});

test('exact half-session seconds survive display and parsing', () => {
	assert.equal(timetableClock(8 * 3600 + 55 * 30), '08:27:30');
	assert.equal(clockSeconds('08:27:30'), 30450);
});

test('calendar creation uses the requested school hours, session, self and recess defaults', () => {
	const settings = defaultTimetableSettings(2026);
	assert.equal(settings.day_start, 28800);
	assert.equal(settings.day_end, 68100);
	assert.equal(settings.session_minutes, 55);
	assert.deepEqual(settings.breaks, [
		{ start: 35400, end: 36600 },
		{ start: 57000, end: 58200 }
	]);
	assert.equal(settings.lunch_start, 43200);
	assert.equal(settings.lunch_end, 50400);
});

test('daily layout exposes incomplete sessions and does not count overlapping pauses twice', () => {
	const settings = { ...defaultTimetableSettings(2026), day_end: 68400 };
	assert.deepEqual(timetableDayBalance(settings), {
		sessions: 9,
		remainingSeconds: 300,
		teachingSeconds: 30000
	});
	assert.deepEqual(
		timetableDayBalance({ ...settings, day_end: 41400, session_minutes: 60, breaks: [] }),
		{ sessions: 3, remainingSeconds: 1800, teachingSeconds: 12600 }
	);
	assert.equal(timetableDayBalance({ ...settings, day_end: 68100 })?.remainingSeconds, 0);
	assert.equal(
		timetableDayBalance({ ...settings, breaks: [...settings.breaks, { start: 45000, end: 46800 }] })
			?.teachingSeconds,
		30000
	);
	assert.equal(timetableDayBalance({ ...settings, session_minutes: 0 }), null);
});

test('school year focus follows September 1 rather than catalogue creation order', () => {
	const years = [
		{ school_year: 2028 },
		{ school_year: 2026 },
		{ school_year: 2027 },
		{ school_year: 2025 }
	];
	assert.equal(currentSchoolYear('2026-08-31'), 2025);
	assert.equal(preferredSchoolYear(years, '2026-08-31'), 2025);
	assert.equal(preferredSchoolYear(years, '2026-09-01'), 2026);
	assert.equal(preferredSchoolYear(years, '2027-01-01'), 2026);
	assert.equal(
		preferredSchoolYear(
			years.filter((year) => year.school_year >= 2027),
			'2026-10-01'
		),
		2027
	);
});
test('civil week arithmetic crosses years and daylight-saving boundaries', () => {
	assert.equal(mondayOf('2026-09-01'), '2026-08-31');
	assert.equal(shiftTimetableDate('2026-10-25', 1), '2026-10-26');
	assert.equal(isoWeek('2027-01-01'), 53);
	assert.equal(isoWeek('2026-09-07'), 37);
});

const members: TimetableMember[] = [1, 2].map((id) => ({
	id,
	name: `Élève ${id}`,
	roles: ['user'],
	promotion_ids: [1],
	assignments: [
		{ promotion_id: 1, kind: 'halves', number: id },
		{ promotion_id: 1, kind: 'thirds', number: id },
		{ promotion_id: 1, kind: 'kholles', number: 1 }
	]
}));
const groups: TimetableGroup[] = [
	{ promotion_id: 1, kind: 'halves', number: 1, student_ids: [1] },
	{ promotion_id: 1, kind: 'halves', number: 2, student_ids: [2] },
	{ promotion_id: 1, kind: 'thirds', number: 1, student_ids: [1] },
	{ promotion_id: 1, kind: 'thirds', number: 2, student_ids: [2] },
	{ promotion_id: 1, kind: 'kholles', number: 1, student_ids: [1, 2] }
];

test('student leaves reveal every assigned partition without duplicating pupils inside a group', () => {
	for (const kind of ['kholles', 'thirds', 'halves', null]) {
		const selectedGroups =
			kind === 'kholles'
				? groups
				: kind === 'thirds'
					? groups.filter((group) => group.kind !== 'kholles')
					: kind === 'halves'
						? groups.filter((group) => group.kind === 'halves')
						: [];
		const root = timetableTree('PTSI', 1, members, selectedGroups);
		const leaves = root.children.flatMap((node) =>
			node.kind === 'student' ? [node] : node.children
		);
		assert.deepEqual([...new Set(leaves.map((node) => node.userId))].sort(), [1, 2]);
		for (const node of root.children.filter((node) => node.number)) {
			const group = selectedGroups.find(
				(group) => group.kind === node.kind && group.number === node.number
			)!;
			assert.deepEqual(
				node.children.map((child) => child.userId),
				group.student_ids
			);
		}
		if (kind === 'kholles')
			assert.equal(root.children.find((node) => node.kind === 'kholles')?.label, 'Khôlle 001');
	}
});

test('pedagogical hours use the inclusive five-minute tolerance and preserve half-sessions', () => {
	for (const minutes of [55, 60, 65]) {
		assert.equal(teachingHours(2, minutes), 1);
		assert.equal(teachingHours(4, minutes), 2);
		assert.equal(teachingHours(1, minutes), 0.5);
	}
	assert.equal(teachingHours(2, 54), 0.9);
	assert.equal(teachingHours(2, 66), 1.1);
});

test('typed times snap across breaks while keeping exact half-session seconds', () => {
	const slots: [number, number][] = [
		[28800, 30450],
		[30450, 32100],
		[33750, 35400],
		[36600, 38250]
	];
	assert.equal(nearestTimetableSlot('08:30', slots), 1);
	assert.equal(nearestTimetableSlot('09:50', slots), 3);
	assert.equal(nearestTimetableSlot('07:00', slots), 0);
	assert.equal(nearestTimetableSlot('18:00', slots), 3);
});

test('resizing either border preserves the other boundary across recess-split segments', () => {
	const slots: [number, number][] = [
		[28800, 30450],
		[30450, 32100],
		[32100, 33750],
		[33750, 35400],
		[36600, 38250],
		[38250, 39900],
		[39900, 41550],
		[41550, 43200]
	];
	const first = {
		start: '2026-09-07T08:00:00',
		end: '2026-09-07T09:50:00',
		start_slot: 0,
		duration_slots: 8
	};
	assert.deepEqual(resizedTimetableSlots(first, 30450, 35400, slots), {
		start_slot: 1,
		duration_slots: 7
	});
	const last = { ...first, start: '2026-09-07T10:10:00', end: '2026-09-07T12:00:00' };
	assert.deepEqual(resizedTimetableSlots(last, 36600, 41550, slots), {
		start_slot: 0,
		duration_slots: 7
	});
	assert.deepEqual(resizedTimetableSlots(first, 28800, 35400, slots), {
		start_slot: 0,
		duration_slots: 8
	});
	const short = {
		...first,
		start_slot: 1,
		duration_slots: 2,
		start: '2026-09-07T08:27:30',
		end: '2026-09-07T09:22:30'
	};
	assert.deepEqual(resizedTimetableSlots(short, 28800, 33750, slots), {
		start_slot: 0,
		duration_slots: 3
	});
	assert.deepEqual(resizedTimetableSlots(short, 30450, 35400, slots), {
		start_slot: 1,
		duration_slots: 3
	});
	assert.throws(() => resizedTimetableSlots(first, 28800, 35400, []), /Aucun créneau/);
});

test('subject specialists precede other teachers and each group stays alphabetically ordered', () => {
	const teachers = [
		{ id: 1, name: 'Zoé', subject_ids: [1] },
		{ id: 2, name: 'Alice', subject_ids: [2] },
		{ id: 3, name: 'Émile', subject_ids: [1, 2] },
		{ id: 4, name: 'Benoît' }
	];
	assert.deepEqual(
		orderedTimetableTeachers(teachers, 1).map((teacher) => teacher.id),
		[3, 1, 2, 4]
	);
	assert.deepEqual(
		orderedTimetableTeachers(teachers, 2).map((teacher) => teacher.id),
		[2, 3, 4, 1]
	);
	assert.deepEqual(
		teachers.map((teacher) => teacher.id),
		[1, 2, 3, 4]
	);
});

test('course TD and TP choices exclude kholleur-only accounts while kholles retain both roles', () => {
	const teachers = [
		{ id: 1, name: 'Professeur', subject_ids: [1], roles: ['teacher'] },
		{ id: 2, name: 'Khôlleur', subject_ids: [1], roles: ['kholleur'] },
		{ id: 3, name: 'Double rôle', subject_ids: [2], roles: ['teacher', 'kholleur'] },
		{ id: 4, name: 'Sans rôle connu' }
	];
	for (const kind of ['course', 'td', 'tp'] as const)
		assert.deepEqual(
			orderedTimetableTeachers(teachers, 1, kind).map((item) => item.id),
			[1, 3]
		);
	assert.deepEqual(
		orderedTimetableTeachers(teachers.slice(0, 3), 1, 'kholle').map((item) => item.id),
		[2, 1, 3]
	);
});

const conflictEvent = (changes: Partial<TimetableEvent> = {}): TimetableEvent => ({
	id: 'a',
	series_id: 'a',
	source_date: '2026-09-07',
	start: '2026-09-07T08:00:00',
	end: '2026-09-07T10:00:00',
	start_slot: 0,
	duration_slots: 4,
	subject_id: 1,
	teacher_id: 1,
	room_id: 1,
	kind: 'course',
	title: 'A',
	color: '#244BC1',
	teacher: 'Professeur',
	room: 'Salle',
	calendar_id: 1,
	promotion_id: 1,
	year_id: 1,
	target_kind: 'halves',
	target_number: 1,
	...changes
});

test('live conflicts allow two half groups in one room but keep teacher and whole-class warnings', () => {
	const first = conflictEvent();
	const second = conflictEvent({
		id: 'b',
		series_id: 'b',
		title: 'B',
		teacher_id: 2,
		target_number: 2
	});
	assert.deepEqual(timetableConflictDetails([first, second]), []);
	assert.ok(
		timetableConflictDetails([first, { ...second, teacher_id: 1 }])[0].message.includes(
			'enseignant'
		)
	);
	assert.ok(
		timetableConflictDetails([
			first,
			{ ...second, target_kind: 'promotion', target_number: null }
		]).some((warning) => warning.message.includes('salle'))
	);
	assert.ok(
		timetableConflictDetails([
			first,
			second,
			{ ...second, id: 'c', title: 'Autre promotion', promotion_id: 2, teacher_id: 3 }
		]).some((warning) => warning.message.includes('salle'))
	);
});

test('group views include shared and intersecting audiences while excluding other students', () => {
	const root = timetableTree('PTSI', 1, members, groups);
	const half = root.children.find((node) => node.key === 'halves-1')!;
	const event = { promotion_id: 1 } as TimetableEvent;
	assert.ok(nodeReceives(event, half, members));
	assert.ok(nodeReceives({ ...event, target_kind: 'kholles', target_number: 1 }, half, members));
	assert.ok(!nodeReceives({ ...event, target_kind: 'student', target_user_id: 2 }, half, members));
	assert.ok(nodeReceives({ ...event, target_kind: 'student', target_user_id: 1 }, half, members));
});

test('unassigned pupils remain reachable and teaching staff never enter the tree', () => {
	const root = timetableTree(
		'PTSI',
		1,
		[...members, { id: 3, name: 'Professeur', roles: ['teacher'], promotion_ids: [1] }],
		[]
	);
	assert.deepEqual(
		root.children.map((node) => node.userId),
		[1, 2]
	);
	const incomplete = timetableTree('PTSI', 1, members, [groups[0]]);
	assert.equal(incomplete.children.at(-1)?.key, 'unassigned');
	assert.equal(incomplete.children.at(-1)?.children[0].userId, 2);
});

test('overlapping named audiences retain their names and report actual shared pupils', () => {
	const custom: TimetableGroup[] = [
		{ promotion_id: 1, kind: 'custom', number: 10, name: 'German', student_ids: [1] },
		{ promotion_id: 1, kind: 'custom', number: 11, name: 'European section', student_ids: [1, 2] }
	];
	const root = timetableTree('PTSI', 1, members, custom);
	assert.equal(root.children.find((node) => node.key === 'custom-10')?.label, 'German');
	assert.ok(
		!timetableTree('PTSI', 1, members, [{ ...custom[0], is_active: false }]).children.some(
			(node) => node.key === 'custom-10'
		)
	);
	const first = conflictEvent({ target_kind: 'custom', target_number: 10, room_id: null });
	const second = conflictEvent({
		id: 'second',
		series_id: 'second',
		teacher_id: 2,
		target_kind: 'custom',
		target_number: 11,
		room_id: null
	});
	assert.ok(timetableConflictDetails([first, second], custom).length > 0);
	assert.deepEqual(
		timetableConflictDetails([first, second], [custom[0], { ...custom[1], student_ids: [2] }]),
		[]
	);
});
