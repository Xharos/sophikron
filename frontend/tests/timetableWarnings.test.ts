import assert from 'node:assert/strict';
import test from 'node:test';
import {
	warningEventTarget,
	warningEventWhen,
	warningTeachingRole,
	uniqueWarningTargets,
	diagnosticChanges,
	timetableDiagnostics,
	type DiagnosticEntry
} from '../src/lib/timetableWarnings.ts';
import {
	timetableConflictDetails,
	teacherAvailabilityDetails,
	defaultTimetableSettings,
	crossCalendarTeacherConflicts,
	type TeacherCommitment,
	type TimetableEvent,
	type TimetableYear,
	type TimetableBoard
} from '../src/lib/timetable.ts';

const event: TimetableEvent = {
	id: 'event-1',
	series_id: 'series-1',
	source_date: '2026-09-07',
	start: '2026-09-07T08:00:00+02:00',
	end: '2026-09-07T08:55:00+02:00',
	start_slot: 0,
	duration_slots: 2,
	subject_id: 1,
	teacher_id: 2,
	room_id: null,
	kind: 'td',
	title: 'Maths',
	color: '#244BC1',
	teacher: 'Professeur',
	room: '',
	year_id: 1,
	calendar_id: 1,
	promotion_id: 1
};

test('confirmation diagnostics show only additions, resolutions and changed balance', () => {
	const warning: DiagnosticEntry = {
		code: 'lunch-2026-09-07',
		severity: 'critical',
		message: 'No lunch'
	};
	const balance: DiagnosticEntry = {
		code: 'balance-1-tp-halves',
		severity: 'warning',
		message: 'A 1 / B 2'
	};
	const unchanged: DiagnosticEntry = {
		code: 'promotion-1',
		severity: 'warning',
		message: 'Unassigned'
	};
	assert.deepEqual(
		diagnosticChanges([warning, unchanged], [unchanged]).map((entry) => entry.change),
		['removed']
	);
	assert.equal(diagnosticChanges([], [warning])[0].change, 'added');
	const changes = diagnosticChanges(
		[balance, unchanged],
		[{ ...balance, message: 'A 2 / B 3' }, unchanged]
	);
	assert.equal(changes.length, 1);
	assert.equal(changes[0].change, 'changed');
	assert.equal(changes[0].previous?.message, balance.message);
	assert.deepEqual(diagnosticChanges([unchanged], [unchanged]), []);
});

test('changing recurrence identifiers does not invent a new teacher conflict', () => {
	const a: DiagnosticEntry = {
		identity: 'availability-2:edited',
		code: 'availability-2:' + 'a'.repeat(32),
		severity: 'warning',
		message: 'Unavailable',
		events: [event]
	};
	const b = {
		...a,
		code: 'availability-2:' + 'b'.repeat(32),
		events: [{ ...event, series_id: 'b'.repeat(32) }]
	};
	assert.deepEqual(diagnosticChanges([a], [b]), []);
});

test('a later occurrence preview reports relevant conflicts while hiding unrelated weeks', () => {
	const second = {
		...event,
		id: 'second',
		school_year: 2026,
		source_date: '2026-09-14',
		start: '2026-09-14T08:00:00+02:00',
		end: '2026-09-14T08:55:00+02:00'
	};
	const board: TimetableBoard = {
		years: [],
		events: [{ ...event, school_year: 2026 }, second],
		members: [],
		warnings: [],
		availability: [{ teacher_id: 2, school_year: 2026, ranges: [] }]
	};
	const entries = timetableDiagnostics(board, '2026-09-01', {
		event: second,
		block: null,
		scope: 'future',
		originalSeries: [event.series_id]
	});
	assert.equal(entries.length, 1);
	assert.equal(entries[0].events?.[0].source_date, '2026-09-14');
	assert.ok(!entries[0].message.includes('2026-09-07'));
});
const year: TimetableYear = {
	id: 1,
	calendar_id: 1,
	school_year: 2026,
	revision: null,
	settings: defaultTimetableSettings(2026),
	slots: [
		[28800, 30450],
		[30450, 32100]
	],
	weeks: {},
	series: [
		{
			start_slot: 0,
			duration_slots: 2,
			subject_id: 1,
			teacher_id: 2,
			room_id: null,
			kind: 'td',
			title: 'Maths',
			interval: 1,
			id: event.series_id,
			lineage: 'lineage-1',
			starts_on: '2026-09-07',
			until: null,
			exceptions: {}
		}
	]
};

test('warning tags prefer the teaching role matching the session type, preserving archived roles', () => {
	assert.equal(warningTeachingRole('td', ['admin', 'teacher', 'kholleur']), 'teacher');
	assert.equal(warningTeachingRole('kholle', ['teacher', 'kholleur']), 'kholleur');
	assert.equal(warningTeachingRole('kholle', ['teacher']), 'teacher');
	assert.equal(warningTeachingRole('td', []), null);
});

test('structured conflict and availability warnings retain first future event identities', () => {
	const other = { ...event, id: 'other-event', series_id: 'other-series' };
	const conflict = timetableConflictDetails([event, other], [], '2026-09-07');
	assert.ok(conflict.length);
	assert.deepEqual(
		conflict[0].events.map((item) => item.id),
		[event.id, other.id]
	);
	const availability = teacherAvailabilityDetails(
		[event],
		[{ teacher_id: 2, school_year: 2026, ranges: [] }],
		'2026-09-07',
		2026
	);
	assert.equal(availability.length, 1);
	assert.equal(availability[0].events[0].id, event.id);
	assert.deepEqual(
		teacherAvailabilityDetails(
			[event],
			[{ teacher_id: 2, school_year: 2026, ranges: [] }],
			'2026-09-08',
			2026
		),
		[]
	);
});

const booking: TeacherCommitment = {
	teacher_id: 2,
	calendar_id: 9,
	calendar_label: 'Deuxième année',
	year_id: 9,
	series_id: 'external',
	conflict_key: 'external-key',
	source_date: event.source_date,
	start: event.start,
	end: event.end
};

test('external teacher conflicts are critical in both calendars and deduplicate recurring segments', () => {
	const repeated = ['2026-09-07', '2026-09-14'].map((day) => ({
		...event,
		source_date: day,
		start: `${day}T08:00:00`,
		end: `${day}T08:55:00`
	}));
	const bookings = repeated.map((item) => ({
		...booking,
		start: item.start,
		end: item.end,
		source_date: item.source_date
	}));
	const warnings = crossCalendarTeacherConflicts(
		[...repeated, repeated[0]],
		[...bookings, bookings[0]],
		'2026-09-07'
	);
	assert.equal(warnings.length, 1);
	assert.equal(warnings[0].severity, 'critical');
	assert.match(warnings[0].summary, /calendrier 9 \(Deuxième année\)/);
	const reverse = { ...event, calendar_id: 9 };
	assert.equal(
		crossCalendarTeacherConflicts(
			[reverse],
			[{ ...booking, calendar_id: 1, calendar_label: 'Première année' }],
			'2026-09-07'
		).length,
		1
	);
	assert.deepEqual(crossCalendarTeacherConflicts([event], [booking], '2026-09-08'), []);
	assert.deepEqual(
		crossCalendarTeacherConflicts([event], [{ ...booking, teacher_id: 3 }], '2026-09-07'),
		[]
	);
	assert.deepEqual(
		crossCalendarTeacherConflicts([event], [{ ...booking, calendar_id: 1 }], '2026-09-07'),
		[]
	);
});

test('touching segment borders and recess gaps do not create teacher collisions', () => {
	assert.deepEqual(
		crossCalendarTeacherConflicts([event], [{ ...booking, start: event.end }], '2026-09-07'),
		[]
	);
	assert.deepEqual(
		timetableConflictDetails([
			event,
			{
				...event,
				id: 'next',
				series_id: 'next',
				start: event.end.slice(0, 19),
				end: '2026-09-07T09:50:00'
			}
		]),
		[]
	);
	const split = [
		event,
		{ ...event, id: 'after-pause', start: '2026-09-07T10:10:00', end: '2026-09-07T11:05:00' }
	];
	assert.deepEqual(
		crossCalendarTeacherConflicts(
			split,
			[{ ...booking, start: '2026-09-07T09:50:00', end: '2026-09-07T10:10:00' }],
			'2026-09-07'
		),
		[]
	);
});

test('whole classes overlap courses and kholles, while disjoint audiences remain possible', () => {
	const other = { ...event, id: 'other', series_id: 'other', teacher_id: 3 };
	const groups = [
		{ promotion_id: 1, kind: 'halves' as const, number: 1, student_ids: [1, 2] },
		{ promotion_id: 1, kind: 'kholles' as const, number: 2, student_ids: [3] },
		{ promotion_id: 1, kind: 'thirds' as const, number: 1, student_ids: [2, 3] }
	];
	for (const kind of ['course', 'kholle'] as const) {
		const conflicts = timetableConflictDetails(
			[event, { ...other, kind, target_kind: 'kholles', target_number: 2 }],
			groups
		);
		assert.equal(conflicts.length, 1);
		assert.equal(conflicts[0].severity, 'critical');
	}
	for (const family of ['halves', 'thirds', 'kholles'] as const) {
		assert.deepEqual(
			timetableConflictDetails(
				[
					{ ...event, target_kind: family, target_number: 1 },
					{ ...other, target_kind: family, target_number: 2 }
				],
				groups
			),
			[]
		);
	}
	assert.deepEqual(
		timetableConflictDetails(
			[
				{ ...event, target_kind: 'halves', target_number: 1 },
				{ ...other, target_kind: 'kholles', target_number: 2 }
			],
			groups
		),
		[]
	);
	assert.equal(
		timetableConflictDetails(
			[
				{ ...event, target_kind: 'halves', target_number: 1 },
				{ ...other, target_kind: 'thirds', target_number: 1 }
			],
			groups
		)[0].severity,
		'critical'
	);
	assert.equal(
		timetableConflictDetails([
			{ ...event, promotion_id: null },
			{ ...other, promotion_id: null }
		])[0].severity,
		'critical'
	);
});

test('warning navigation keeps recurrences grouped and exceptions independently dated', () => {
	const normal = warningEventTarget(event, year);
	assert.equal(normal.recurrenceKey, 'lineage-1');
	const exception = warningEventTarget({ ...event, is_exception: true }, year);
	assert.equal(exception.recurrenceKey, undefined);
	assert.equal(
		uniqueWarningTargets([normal, { ...normal, event: { ...event, id: 'segment-2' } }]).length,
		1
	);
	assert.equal(warningEventWhen(exception, year), 'lundi 7 septembre 2026 · 08:00–08:55');
});

test('default availability includes weekday noon but ends Saturday at twelve', () => {
	assert.deepEqual(
		teacherAvailabilityDetails(
			[{ ...event, start: '2026-09-07T12:00:00', end: '2026-09-07T13:00:00' }],
			[],
			undefined,
			2026
		),
		[]
	);
	assert.equal(
		teacherAvailabilityDetails(
			[{ ...event, start: '2026-09-12T12:00:00', end: '2026-09-12T13:00:00' }],
			[],
			undefined,
			2026
		).length,
		1
	);
});
