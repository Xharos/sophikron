import assert from 'node:assert/strict';
import test from 'node:test';
import {
	selectTeachers,
	teacherColor,
	teacherCalendarColor,
	teacherSubjectHours,
	teacherCalendarHours
} from '../src/lib/teacherTimetable.ts';
import {
	timetableConflicts,
	teacherAvailabilityWarnings,
	type TimetableEvent
} from '../src/lib/timetable.ts';

test('teacher hours retain each annual calendar’s own session length', () => {
	assert.equal(teacherSubjectHours([event('2026-09-07', { session_minutes: 55 })], 60)[0].total, 1);
	assert.equal(
		teacherSubjectHours(
			[
				event('2026-09-07', {
					session_minutes: 72,
					end: '2026-09-07T09:12:00+02:00'
				})
			],
			60
		)[0].total,
		1.2
	);
});

test('teacher calendar rows retain types, actual durations and the weekly sum', () => {
	const course = event('2026-09-07', { calendar_label: 'PTSI · 2026', session_minutes: 55 });
	const option = event('2026-09-08', {
		calendar_id: 2,
		calendar_label: 'PT · 2026',
		kind: 'kholle'
	});
	const rows = teacherCalendarHours([course, course, option], 60);
	assert.equal(rows.length, 2);
	assert.equal(rows.find((row) => row.calendarId === 1)?.course, 1);
	assert.equal(rows.find((row) => row.calendarId === 2)?.kholle, 55 / 60);
	assert.equal(
		rows.reduce((sum, row) => sum + row.total, 0),
		1 + 55 / 60
	);
});

test('calendar and subject rows reconcile with subject subtotals and the overall total', () => {
	const sessions = [
		event('2026-09-07', { calendar_label: 'PTSI', session_minutes: 55 }),
		event('2026-09-08', {
			calendar_label: 'PTSI',
			subject_id: 2,
			kind: 'kholle',
			session_minutes: 55
		}),
		event('2026-09-09', { calendar_id: 2, calendar_label: 'PT', kind: 'td', session_minutes: 55 }),
		event('2026-09-10', {
			calendar_id: 2,
			calendar_label: 'PT',
			subject_id: null,
			kind: 'tp',
			session_minutes: 55
		})
	];
	sessions.push(sessions[0]);
	const rows = teacherCalendarHours(sessions, 55);
	assert.equal(rows.length, 4);
	assert.equal(rows.find((row) => row.calendarId === 1 && row.subjectId === 1)?.course, 1);
	assert.equal(rows.find((row) => row.calendarId === 1 && row.subjectId === 2)?.kholle, 1);
	const totals = teacherSubjectHours(sessions, 55);
	assert.equal(totals.find((row) => row.subjectId === 1)?.total, 2);
	for (const total of totals)
		for (const kind of ['course', 'td', 'tp', 'kholle', 'total'] as const) {
			assert.equal(
				rows
					.filter((row) => row.subjectId === total.subjectId)
					.reduce((sum, row) => sum + row[kind], 0),
				total[kind]
			);
		}
	assert.equal(
		rows.reduce((sum, row) => sum + row.total, 0),
		4
	);
});

function event(day: string, overrides: Partial<TimetableEvent> = {}): TimetableEvent {
	return {
		id: `a-${day}`,
		series_id: 'a',
		conflict_key: 'pattern-a',
		source_date: day,
		start: `${day}T08:00:00+02:00`,
		end: `${day}T08:55:00+02:00`,
		start_slot: 0,
		duration_slots: 2,
		subject_id: 1,
		teacher_id: 2,
		room_id: null,
		kind: 'course',
		title: 'Mathématiques',
		color: '#244BC1',
		teacher: 'Professeur',
		room: '',
		calendar_id: 1,
		promotion_id: null,
		year_id: 1,
		school_year: 2026,
		...overrides
	};
}

test('individual selection, Ctrl toggle and complete subject selection share one roster', () => {
	assert.deepEqual(selectTeachers([1], [2], false), [2]);
	assert.deepEqual(selectTeachers([1], [2], true), [1, 2]);
	assert.deepEqual(selectTeachers([1, 2], [1], true), [2]);
	assert.deepEqual(selectTeachers([1, 2], [1, 2], true), []);
	assert.deepEqual(selectTeachers([1], [2, 3], true), [1, 2, 3]);
	assert.match(teacherColor(1), /^#[a-f\d]{6}$/i);
	assert.equal(teacherColor(1), teacherColor(1));
});

test('calendar shades stay stable across selections while retaining the teacher hue', () => {
	const colors = [1, 2, 3, 4, 5].map((id) => teacherCalendarColor(2, id));
	assert.equal(new Set(colors).size, 5);
	assert.equal(teacherCalendarColor(2, 1), colors[0]);
	assert.notEqual(teacherCalendarColor(3, 1), colors[0]);
	for (const color of colors) {
		assert.match(color, /^#[a-f\d]{6}$/i);
		const base = [1, 3, 5].map((index) =>
			Number.parseInt(teacherColor(2).slice(index, index + 2), 16)
		);
		const ratios = [1, 3, 5].map(
			(index, channel) => Number.parseInt(color.slice(index, index + 2), 16) / base[channel]
		);
		assert.ok(Math.max(...ratios) - Math.min(...ratios) < 0.03);
	}
});

test('teacher hours include kholles, all assigned groups and split segments, sorted by total', () => {
	const events = [
		event('2026-09-07', { id: 'a', target_kind: 'halves', target_number: 1 }),
		event('2026-09-07', { id: 'b', kind: 'td', target_kind: 'halves', target_number: 2 }),
		event('2026-09-07', { id: 'c', kind: 'tp', subject_id: 2 }),
		event('2026-09-07', { id: 'd', kind: 'kholle', subject_id: 2 }),
		event('2026-09-07', {
			id: 'e',
			kind: 'kholle',
			subject_id: 2,
			end: '2026-09-07T08:27:30+02:00'
		})
	];
	const rows = teacherSubjectHours([...events, events[0]], 55);
	assert.equal(rows[0].subjectId, 2);
	assert.equal(rows[0].total, 2.5);
	assert.equal(rows[0].kholle, 1.5);
	assert.equal(rows[1].course, 1);
	assert.equal(rows[1].td, 1);
	assert.equal(rows[1].total, 2);
});

test('future warnings deduplicate stable recurring pairs and respect availability boundaries', () => {
	const events = ['2026-09-07', '2026-09-14', '2026-09-21'].flatMap((day) => [
		event(day),
		event(day, { id: `b-${day}`, series_id: 'b', conflict_key: 'pattern-b' })
	]);
	const conflicts = timetableConflicts(events, [], '2026-09-10');
	assert.equal(conflicts.length, 2); // One teacher conflict and one full-class conflict per recurring pair.
	assert.match(conflicts[0], /2026-09-14/);
	assert.deepEqual(timetableConflicts(events.slice(0, 2), [], '2026-09-10'), []);
	const pattern = [{ teacher_id: 2, school_year: 2026, ranges: [] }];
	assert.equal(teacherAvailabilityWarnings(events, pattern, '2026-09-10').length, 2);
	assert.deepEqual(
		teacherAvailabilityWarnings(
			events,
			[{ ...pattern[0], ranges: [{ weekday: 0, start: 28800, end: 32100 }] }],
			'2026-09-10'
		),
		[]
	);
	assert.deepEqual(teacherAvailabilityWarnings(events, [], '2026-09-10'), []);
});
