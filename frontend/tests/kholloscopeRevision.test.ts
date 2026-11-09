import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
	groupedRevisionChanges,
	isRevisionMonday,
	revisionChange
} from '../src/lib/kholloscopeRevision.ts';
import type { GeneratedSession } from '../src/lib/kholloscopeGeneration.ts';

test('revision boundary accepts civil Mondays across DST and rejects invalid dates', () => {
	assert.equal(isRevisionMonday('2026-10-26'), true);
	assert.equal(isRevisionMonday('2026-03-30'), true);
	for (const value of ['', '2026-10-27', '2026-02-30', '2026-13-01'])
		assert.equal(isRevisionMonday(value), false);
});

test('recurring replacements are grouped while different teachers and slots stay separate', () => {
	const source: GeneratedSession = {
		id: 'a',
		calendar_id: 1,
		subject_id: 1,
		teacher_id: 1,
		room_id: 1,
		day: '2026-11-09',
		start: 28800,
		end: 32100,
		group: 1
	};
	const changes = ['2026-11-09', '2026-11-16', '2026-11-23'].map((day) => ({
		before: { ...source, day },
		after: { ...source, day, teacher_id: 2, room_id: 2 }
	}));
	const grouped = groupedRevisionChanges([
		...changes,
		{ before: source, after: { ...source, teacher_id: 3 } },
		{ before: { ...source, day: '2026-11-10' }, after: null }
	]);
	assert.equal(grouped.length, 3);
	const recurring = grouped.find((g) => g.count === 3)!;
	assert.equal(recurring.first, '2026-11-09');
	assert.equal(recurring.last, '2026-11-23');
	assert.equal(grouped.find((g) => !g.after)?.count, 1);
});

test('review distinguishes replacement, room changes, moves and added sessions', () => {
	const session: GeneratedSession = {
		id: 'a',
		calendar_id: 1,
		subject_id: 1,
		teacher_id: 1,
		room_id: 1,
		day: '2026-11-09',
		start: 28800,
		end: 32100,
		group: 1
	};
	assert.equal(revisionChange(null, session), 'Ajout');
	assert.equal(revisionChange(session, { ...session, teacher_id: 2 }), 'Remplacement');
	assert.equal(revisionChange(session, { ...session, room_id: 2 }), 'Changement de salle');
	assert.equal(revisionChange(session, { ...session, start: 32100, end: 35400 }), 'Déplacement');
});
