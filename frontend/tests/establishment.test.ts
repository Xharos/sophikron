import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	calendarLegend,
	parisDay,
	timelineProgress,
	timelineEventEnd,
	timelineStats,
	timelineMonths,
	type Timeline,
	type TimelineEvent
} from '../src/lib/site.ts';

test('calendar progression uses inclusive bounds and clamps outside the school year', () => {
	assert.equal(timelineProgress('2026-09-01', '2026-09-10', '2026-08-31'), 0);
	assert.equal(timelineProgress('2026-09-01', '2026-09-10', '2026-09-01'), 0);
	assert.equal(timelineProgress('2026-09-01', '2026-09-10', '2026-09-06'), 50);
	assert.equal(timelineProgress('2026-09-01', '2026-09-10', '2026-09-10'), 90);
	assert.equal(timelineProgress('2026-09-01', '2026-09-10', '2026-09-11'), 100);
	assert.equal(timelineProgress('2026-09-01', '2026-09-01', '2026-09-02'), 100);
	assert.equal(timelineEventEnd('9999-09-01', '9999-12-31', '9999-12-31'), 100);
});

test('the public calendar follows Paris midnight through summer time and winter changes', () => {
	assert.equal(parisDay(new Date('2026-08-31T22:30:00Z')), '2026-09-01');
	assert.equal(parisDay(new Date('2026-12-31T23:30:00Z')), '2027-01-01');
	assert.equal(parisDay(new Date('2026-10-25T00:30:00Z')), '2026-10-25');
	assert.equal(parisDay(new Date('2026-10-25T01:30:00Z')), '2026-10-25');
});

const bar: Timeline = {
	id: 1,
	name: 'Test',
	starts_on: '2026-10-19',
	ends_on: '2026-11-01',
	color: '#123456',
	version: 0
};
function holiday(
	start: string,
	end: string,
	bars = [1],
	kind: TimelineEvent['kind'] = 'holiday'
): TimelineEvent {
	return {
		...bar,
		id: 2,
		name: 'Vacances',
		starts_on: start,
		ends_on: end,
		timeline_ids: bars,
		kind
	};
}
test('remaining inclusive days exclude weekends and the union of assigned vacations only', () => {
	const events = [
		holiday('2026-10-21', '2026-10-25'),
		holiday('2026-10-23', '2026-10-27'),
		holiday('2026-10-19', '2026-11-01', [2]),
		holiday('2026-10-28', '2026-10-29', [1], 'oral')
	];
	const stats = timelineStats(bar, events, '2026-10-25');
	assert.equal(stats.totalDays, 14);
	assert.equal(stats.remainingDays, 8);
	assert.equal(stats.totalWorkingDays, 5);
	assert.equal(stats.remainingWorkingDays, 3);
	assert.equal(timelineStats(bar, events, '2026-10-18').remainingWorkingDays, 5);
	assert.equal(timelineStats(bar, events, '2026-11-02').remainingWorkingDays, 0);
	assert.equal(timelineStats(bar, events, '2026-11-02').remainingDays, 0);
	assert.equal(timelineStats({ ...bar, id: 2 }, events, '2026-10-25').remainingWorkingDays, 0);
});
test('working-day counts handle leap days, a single day, partial holidays and the current school day', () => {
	const leap = { ...bar, starts_on: '2024-02-28', ends_on: '2024-03-04' };
	assert.equal(timelineStats(leap, [], '2024-02-29').remainingDays, 5);
	assert.equal(timelineStats(leap, [], '2024-02-29').remainingWorkingDays, 3);
	assert.equal(
		timelineStats(leap, [holiday('2024-02-01', '2024-02-29')], '2024-02-28').totalWorkingDays,
		2
	);
	const monday = { ...bar, starts_on: '2026-10-19', ends_on: '2026-10-19' };
	assert.equal(timelineStats(monday, [], '2026-10-19').remainingWorkingDays, 1);
	assert.equal(timelineStats(monday, [], '2026-10-20').remainingWorkingDays, 0);
	assert.equal(
		timelineStats(monday, [holiday('2026-10-19', '2026-10-19')], '2026-10-19').remainingWorkingDays,
		0
	);
});
test('monthly slices follow real month lengths across year and leap-year boundaries', () => {
	const months = timelineMonths('2023-12-20', '2024-03-04');
	assert.equal(months.length, 4);
	assert.ok(Math.abs(months.reduce((sum, month) => sum + month.width, 0) - 100) < 1e-10);
	assert.ok(months[1].width > months[2].width);
	assert.match(months[0].title, /2023/);
	assert.match(months[1].title, /2024/);
	assert.equal(timelineMonths('2026-09-01', '2027-08-31').length, 12);
	assert.equal(timelineMonths('9999-12-01', '9999-12-31')[0].width, 100);
});

test('holidays share one legend and configured color while individual events remain distinct', () => {
	const events = [
		holiday('2026-10-21', '2026-10-25'),
		{ ...holiday('2026-12-20', '2027-01-03', [1, 2]), id: 3, name: 'Noël', color: '#FFFFFF' },
		{ ...holiday('2026-10-28', '2026-10-29', [1], 'oral'), id: 4, name: 'Oraux', color: '#112233' },
		{ ...holiday('2026-10-30', '2026-10-30', [2], 'school'), id: 5, name: 'Fête', color: '#445566' }
	];
	const legend = calendarLegend(events, '#ABCDEF');
	assert.equal(legend.length, 3);
	assert.deepEqual(legend[0], { key: 'holiday', label: 'Vacances', color: '#ABCDEF' });
	assert.deepEqual(
		legend.slice(1).map((entry) => entry.color),
		['#112233', '#445566']
	);
	assert.equal(legend[1].event, events[2]);
	assert.deepEqual(calendarLegend([], '#123456'), []);
	assert.equal(events[1].name, 'Noël');
});
