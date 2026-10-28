import assert from 'node:assert/strict';
import test from 'node:test';
import {
	clockSeconds,
	currentSchoolYear,
	preferredSchoolYear,
	defaultTimetableSettings,
	timetableDayBalance,
	isoWeek,
	mondayOf,
	shiftTimetableDate,
	timetableClock,
	timetableTree,
	nodeReceives,
	teachingHours,
	nearestTimetableSlot,
	resizedTimetableSlots,
	orderedTimetableTeachers,
	timetableAudienceLabel,
	timetableConflicts,
	type TimetableMember,
	type TimetableGroup,
	type TimetableEvent
} from '../src/lib/timetable.ts';

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
	assert.deepEqual(timetableConflicts([first, second]), []);
	assert.ok(timetableConflicts([first, { ...second, teacher_id: 1 }])[0].includes('enseignant'));
	assert.ok(
		timetableConflicts([first, { ...second, target_kind: 'promotion', target_number: null }]).some(
			(warning) => warning.includes('salle')
		)
	);
	assert.ok(
		timetableConflicts([
			first,
			second,
			{ ...second, id: 'c', title: 'Autre promotion', promotion_id: 2, teacher_id: 3 }
		]).some((warning) => warning.includes('salle'))
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
	assert.ok(timetableConflicts([first, second], custom).length > 0);
	assert.deepEqual(
		timetableConflicts([first, second], [custom[0], { ...custom[1], student_ids: [2] }]),
		[]
	);
});
