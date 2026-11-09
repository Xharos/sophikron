import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	colloscopeRows,
	defaultGenerationRules,
	generationTimeTotal,
	matchesSession,
	validGroupMapping,
	type GeneratedSession,
	type GenerationGroups
} from '../src/lib/kholloscopeGeneration.ts';

const session: GeneratedSession = {
	id: 'session',
	calendar_id: 1,
	subject_id: 2,
	teacher_id: 3,
	room_id: 4,
	group: 5,
	day: '2027-04-21',
	original_day: '2027-04-16',
	start: 43200,
	end: 46500
};

test('new generation forms enable improvement by default', () => {
	assert.equal(defaultGenerationRules.optimize, true);
	assert.equal(defaultGenerationRules.time_limit, 900);
	assert.deepEqual(
		[
			defaultGenerationRules.time_stability_percent,
			defaultGenerationRules.time_weekly_percent,
			defaultGenerationRules.time_rotation_percent,
			defaultGenerationRules.time_annual_percent
		],
		[5, 20, 70, 5]
	);
	assert.equal(generationTimeTotal(defaultGenerationRules), 100);
	assert.equal(generationTimeTotal({ ...defaultGenerationRules, time_stability_percent: 6 }), 101);
});

test('calendar filters combine resources and distinguish unassigned groups', () => {
	const filters = { calendar: 1, teacher: 3, subject: 2, room: 4, group: 5 };
	assert.equal(matchesSession(session, filters), true);
	for (const key of Object.keys(filters) as (keyof typeof filters)[]) {
		assert.equal(matchesSession(session, { ...filters, [key]: 99 }), false);
	}
	assert.equal(matchesSession({ ...session, group: undefined }, filters), false);
	assert.equal(
		matchesSession(session, { calendar: 0, teacher: 0, subject: 0, room: 0, group: 0 }),
		true
	);
});

test('colloscope shows group rotation across recurring slots and retains empty weeks', () => {
	const nextWeek = { ...session, id: 'next', group: 7, day: '2027-04-28' };
	const simultaneous = { ...session, id: 'parallel', group: 2 };
	const recovered = { ...session, id: 'recovered', day: '2027-04-23' };
	const table = colloscopeRows(
		[session, nextWeek, simultaneous, recovered, { ...session, group: undefined }],
		['2027-04-12', '2027-04-19', '2027-04-26']
	);
	assert.deepEqual(table.weeks, ['2027-04-12', '2027-04-19', '2027-04-26']);
	assert.equal(table.rows.length, 2);
	assert.deepEqual(table.rows[0].cells.get('2027-04-19'), [simultaneous, session]);
	assert.deepEqual(table.rows[0].cells.get('2027-04-26'), [nextWeek]);
	assert.equal(table.rows[0].cells.has('2027-04-12'), false);
	assert.deepEqual(table.rows[1].cells.get('2027-04-19'), [recovered]);
});

test('colloscope uses civil weeks across a year boundary', () => {
	const table = colloscopeRows([{ ...session, day: '2027-01-01' }]);
	assert.deepEqual(table.weeks, ['2026-12-28']);
	assert.equal(table.rows[0].weekday, 4);
});

test('a rotation mapping is a complete per-promotion bijection', () => {
	const choices: GenerationGroups = {
		revision: 'a',
		schedule: [],
		mappings: [],
		calendars: [{ id: 1, name: 'PTSI', groups: [2, 5], tracks: 2 }]
	};
	assert.equal(
		validGroupMapping(choices, [
			{ calendar_id: 1, track: 1, group: 5 },
			{ calendar_id: 1, track: 2, group: 2 }
		]),
		true
	);
	assert.equal(validGroupMapping(choices, []), false);
	assert.equal(
		validGroupMapping(choices, [
			{ calendar_id: 1, track: 1, group: 2 },
			{ calendar_id: 1, track: 2, group: 2 }
		]),
		false
	);
	assert.equal(
		validGroupMapping(choices, [
			{ calendar_id: 9, track: 1, group: 2 },
			{ calendar_id: 1, track: 2, group: 5 }
		]),
		false
	);
});
