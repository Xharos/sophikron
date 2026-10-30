import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createKholleGroup, groupError, groupLabel, moveStudent } from '../src/lib/groups.ts';
import { promotionCounts } from '../src/lib/dashboard.ts';

test('partition names distinguish letters from padded khôlle numbers', () => {
	assert.equal(groupLabel('halves', 1), 'Groupe A');
	assert.equal(groupLabel('thirds', 1), 'Groupe X');
	assert.equal(groupLabel('thirds', 2), 'Groupe Y');
	assert.equal(groupLabel('thirds', 3), 'Groupe Z');
	assert.equal(groupLabel('kholles', 1), 'Groupe 01');
	assert.equal(groupLabel('kholles', 12), 'Groupe 12');
});

test('extracting a pair or a singleton keeps other khôlles and their numbers intact', () => {
	const initial = [
		{ number: 1, x: 20, y: 20, student_ids: [1, 2] },
		{ number: 7, x: 320, y: 20, student_ids: [3, 4, 5] }
	];
	const split = createKholleGroup(initial, [1], 620, 20);
	assert.deepEqual(
		split.map((group) => group.student_ids),
		[[2], [1], [3, 4, 5]]
	);
	assert.deepEqual(
		split.find((group) => group.number === 7),
		initial[1]
	);
	assert.deepEqual(initial[0].student_ids, [1, 2]);
	const pair = createKholleGroup(split, [1, 3], 500, 350);
	assert.deepEqual(pair.find((group) => group.number === 2)?.student_ids, [1, 3]);
	assert.deepEqual(pair.find((group) => group.number === 7)?.student_ids, [4, 5]);
	assert.equal(new Set(pair.flatMap((group) => group.student_ids)).size, 5);
	assert.ok(groupError('kholles', split, [1, 2, 3, 4, 5]));
	assert.equal(groupError('kholles', pair, [1, 2, 3, 4, 5], 2), '');
});

test('khôlle creation admits newcomers and archived pupils without duplicating assignments', () => {
	const initial = [{ number: 8, x: 20, y: 20, student_ids: [1, 2, 3] }];
	const added = createKholleGroup(initial, [4], 320, 20);
	assert.equal(groupError('kholles', added, [1, 2, 3, 4]), '');
	const archived = createKholleGroup(added, [5, 6], 620, 20);
	assert.equal(groupError('kholles', archived, [1, 2, 3, 4, 5, 6], 3, [5, 6]), '');
	assert.deepEqual(
		archived.find((group) => group.number === 8),
		initial[0]
	);
	assert.equal(createKholleGroup(initial, [1, 1], 0, 0), initial);
	assert.equal(createKholleGroup(initial, [], 0, 0), initial);
});

test('khôlle creation respects number limits and preserves deliberately empty bubbles', () => {
	const full = Array.from({ length: 1000 }, (_, index) => ({
		number: index + 1,
		x: 0,
		y: 0,
		student_ids: [index + 1]
	}));
	assert.equal(createKholleGroup(full, [1001], 0, 0), full);
	const moved = createKholleGroup(full, [1], -5, 1000001);
	assert.equal(moved.length, 1000);
	assert.deepEqual(moved[0], { number: 1, x: 0, y: 1000000, student_ids: [1] });
	const empty = { number: 1, x: 0, y: 0, student_ids: [] };
	assert.deepEqual(createKholleGroup([empty], [2], 1, 2)[0], empty);
});

test('archived assignments remain movable but never affect balancing', () => {
	const groups = [
		{ number: 1, x: 0, y: 0, student_ids: [1, 2, 3, 7] },
		{ number: 2, x: 0, y: 0, student_ids: [4, 5, 6] },
		{ number: 15, x: 0, y: 0, student_ids: [8] }
	];
	const roster = Array.from({ length: 8 }, (_, index) => index + 1);
	assert.equal(groupError('kholles', groups, roster, 3, [7, 8]), '');
	assert.ok(groupError('kholles', groups, roster, 3, [8]));
	const draft = moveStudent(groups, 7, 15);
	assert.equal(groupError('kholles', draft, roster, 3, [7, 8]), '');
	assert.equal(groupError('kholles', draft, roster, 3, [7]), '');
	assert.equal(
		groupError('kholles', [{ number: 15, x: 0, y: 0, student_ids: [7, 8] }], [7, 8], 3, [7, 8]),
		''
	);
	const halves = [
		{ number: 1, x: 0, y: 0, student_ids: [1, 2, 4, 5] },
		{ number: 2, x: 0, y: 0, student_ids: [3] }
	];
	assert.equal(groupError('halves', halves, [1, 2, 3, 4, 5], 3, [4, 5]), '');
});

test('promotion counters separate pupils, unique staff accounts and archived members', () => {
	const promotion = {
		id: 1,
		identifier: 'PT',
		year: 2026,
		color: '#123456',
		is_active: true,
		student_count: 45,
		non_archived_student_count: 44,
		teaching_count: 2,
		archived_count: 1
	};
	assert.equal(promotionCounts(promotion), '44 élèves · 2 enseignants · 1 archivé');
	assert.equal(
		promotionCounts({ ...promotion, non_archived_student_count: 45, archived_count: 0 }),
		'45 élèves · 2 enseignants · 0 archivés'
	);
});

test('temporary transfers allow imbalance without changing the saved source', () => {
	const initial = [
		{ number: 1, x: 0, y: 0, student_ids: [1, 2] },
		{ number: 2, x: 300, y: 0, student_ids: [3, 4] }
	];
	const draft = moveStudent(initial, 1, 2);
	assert.deepEqual(initial[0].student_ids, [1, 2]);
	assert.deepEqual(
		draft.map((group) => group.student_ids),
		[[2], [3, 4, 1]]
	);
	assert.ok(groupError('halves', draft, [1, 2, 3, 4]));
	assert.ok(groupError('kholles', draft, [1, 2, 3, 4], 2));
	assert.deepEqual(moveStudent(initial, 1, 99), initial);
});

test('khôlles accept up to five and reject duplicates, empty groups and missing pupils', () => {
	const group = { number: 1, x: 0, y: 0, student_ids: [1, 2, 3, 4, 5] };
	assert.equal(groupError('kholles', [group], group.student_ids, 5), '');
	assert.ok(
		groupError('kholles', [{ ...group, student_ids: [1, 2, 3, 4, 5, 6] }], [1, 2, 3, 4, 5, 6])
	);
	assert.ok(
		groupError('kholles', [group, { number: 2, x: 0, y: 0, student_ids: [] }], group.student_ids)
	);
	assert.ok(groupError('kholles', [{ ...group, student_ids: [1, 1] }], [1, 2]));
	assert.ok(groupError('kholles', [group], [1, 2, 3, 4, 5, 6]));
});

test('khôlle targets are exact except for one division remainder', () => {
	for (const [target, sizes, valid] of [
		[3, Array(15).fill(3), true],
		[3, [5, 1, ...Array(13).fill(3)], false],
		[3, [4, 2, ...Array(13).fill(3)], false],
		[3, [...Array(15).fill(3), 1], true],
		[3, [...Array(14).fill(3), 2, 2], false],
		[3, [3, 2, 2], false],
		[3, [1, 3, 3], true],
		[5, Array(9).fill(5), true],
		[2, [...Array(22).fill(2), 1], true],
		[4, [...Array(11).fill(4), 1], true]
	] as [number, number[], boolean][]) {
		let next = 1;
		const groups = sizes.map((size, index) => ({
			number: index + 1,
			x: 0,
			y: 0,
			student_ids: Array.from({ length: size }, () => next++)
		}));
		const roster = Array.from({ length: next - 1 }, (_, index) => index + 1);
		assert.equal(
			groupError('kholles', groups, roster, target) === '',
			valid,
			`${target}: ${sizes}`
		);
	}
});
