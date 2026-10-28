import assert from 'node:assert/strict';
import test from 'node:test';
import {
	warningEventTarget,
	warningEventWhen,
	warningTeachingRole,
	uniqueWarningTargets
} from '../src/lib/timetableWarnings.ts';
import {
	timetableConflictDetails,
	teacherAvailabilityDetails,
	defaultTimetableSettings,
	crossCalendarTeacherConflicts,
	datedBlockEvents,
	weeklyEvents,
	futureTemplateEvents,
	previewTemplateEvents,
	type TeacherCommitment,
	type TimetableEvent,
	type TimetableYear,
	type WeeklyBlock
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
const block: WeeklyBlock = {
	key: 'weekly-key',
	weekday: 0,
	phase: 1,
	interval: 1,
	start_slot: 0,
	duration_slots: 2,
	subject_id: 1,
	teacher_id: 2,
	room_id: null,
	kind: 'td',
	title: 'Maths'
};
const year: TimetableYear = {
	id: 1,
	calendar_id: 1,
	school_year: 2026,
	revision: null,
	published_revision: null,
	settings: defaultTimetableSettings(2026),
	slots: [
		[28800, 30450],
		[30450, 32100]
	],
	weeks: {},
	series: [
		{
			...block,
			id: event.series_id,
			lineage: 'lineage-1',
			starts_on: '2026-09-07',
			until: null,
			template_key: block.key,
			exceptions: {}
		}
	]
};

test('warning navigation identifies weekly blocks, dated exceptions and independent recurring events', () => {
	assert.equal(warningEventTarget(event, year, [block], false).templateKey, block.key);
	assert.equal(
		warningEventTarget({ ...event, is_exception: true }, year, [block], false).templateKey,
		null
	);
	assert.equal(
		warningEventTarget({ ...event, series_id: block.key }, year, [block], true).templateKey,
		block.key
	);
	assert.equal(warningEventTarget(event, year, [], false).templateKey, null);
	const independent = { ...year, series: [{ ...year.series[0], template_key: null }] };
	const target = warningEventTarget(event, independent, [block], false);
	assert.equal(target.templateKey, null);
	assert.equal(target.recurrenceKey, 'lineage-1');
});

test('weekly labels show weekday and full logical hours; dated labels include the complete date', () => {
	assert.equal(warningEventWhen({ event, templateKey: block.key }, year), 'lundi · 08:00–08:55');
	assert.equal(
		warningEventWhen({ event, templateKey: null }, year),
		'lundi 7 septembre 2026 · 08:00–08:55'
	);
	assert.equal(
		warningEventWhen(
			{ event: { ...event, start_slot: 1, duration_slots: 1 }, templateKey: block.key },
			year
		),
		'lundi · 08:27:30–08:55'
	);
});

test('warning targets merge split sessions and repeated weeks but retain separate dated exceptions', () => {
	const weekly = warningEventTarget(event, year, [block], false);
	assert.equal(
		uniqueWarningTargets([weekly, { ...weekly, event: { ...event, id: 'segment-2' } }]).length,
		1
	);
	const dated = { event, templateKey: null, recurrenceKey: 'lineage-1' };
	const later = {
		...dated,
		event: { ...event, start: '2026-09-14T08:00:00+02:00', source_date: '2026-09-14' }
	};
	assert.equal(uniqueWarningTargets([later, dated]).length, 1);
	assert.equal(
		uniqueWarningTargets([
			{ ...dated, recurrenceKey: undefined },
			{ ...later, recurrenceKey: undefined }
		]).length,
		2
	);
});

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

test('dated and weekly booking previews honor actual cycles, horizons and closed days', () => {
	const annual = {
		...year,
		weeks: { '2026-09-07': 1, '2026-09-14': 2, '2026-09-21': 3, '2026-09-28': 4 }
	};
	const fields = {
		...annual.series[0],
		starts_on: '2026-09-14',
		interval: 2 as const,
		until: '2026-09-28'
	};
	const dated = datedBlockEvents(fields, annual, 1, 'candidate');
	assert.deepEqual(
		dated.map((item) => item.source_date),
		['2026-09-14', '2026-09-28']
	);
	const weekly = { ...block, interval: 2 as const, phase: 2 };
	const projected = futureTemplateEvents(
		weeklyEvents([weekly], annual, '2026-09-07', 1),
		[weekly],
		annual,
		'2026-09-07'
	);
	assert.deepEqual(crossCalendarTeacherConflicts(projected, [booking], '2026-09-07'), []);
	assert.equal(
		crossCalendarTeacherConflicts(
			projected,
			[{ ...booking, start: '2026-09-14T08:00:00', end: '2026-09-14T08:55:00' }],
			'2026-09-07'
		).length,
		1
	);
	assert.deepEqual(
		datedBlockEvents({ ...fields, interval: 0, starts_on: '2026-09-12' }, annual, 1, 'closed'),
		[]
	);
});

test('weekly coherence includes dated kholles and preserves canceled template occurrences', () => {
	const annual = {
		...year,
		weeks: { '2026-09-07': 1, '2026-09-14': 2 },
		series: [{ ...year.series[0], exceptions: { '2026-09-14': null } }]
	};
	const kholle = {
		...event,
		id: 'kholle',
		series_id: 'dated-kholle',
		kind: 'kholle' as const,
		teacher_id: 3,
		target_kind: 'kholles' as const,
		target_number: 1
	};
	const preview = previewTemplateEvents(
		weeklyEvents([block], annual, '2026-09-07', 1),
		[block],
		annual,
		'2026-09-07',
		[event, kholle]
	);
	assert.ok(preview.some((item) => item.id === kholle.id));
	assert.ok(!preview.some((item) => item.source_date === '2026-09-14'));
	assert.equal(timetableConflictDetails(preview, [], '2026-09-07')[0].severity, 'critical');
	const legacyKholle = { ...kholle, template_key: 'legacy-kholle', series_id: 'legacy-series' };
	const legacyYear = {
		...annual,
		series: [
			...annual.series,
			{
				...year.series[0],
				id: 'legacy-series',
				template_key: 'legacy-kholle',
				kind: 'kholle' as const,
				exceptions: {}
			}
		]
	};
	assert.ok(
		previewTemplateEvents(
			weeklyEvents([block], legacyYear, '2026-09-07', 1),
			[block],
			legacyYear,
			'2026-09-07',
			[legacyKholle]
		).some((item) => item.series_id === 'legacy-series')
	);
});
