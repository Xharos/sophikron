import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupError, groupLabel, moveStudent } from '../src/lib/groups.ts';
import { promotionCounts } from '../src/lib/dashboard.ts';

test('partition names distinguish letters from padded khôlle numbers', () => {
	assert.equal(groupLabel('halves', 1), 'Groupe A');
	assert.equal(groupLabel('thirds', 1), 'Groupe X');
	assert.equal(groupLabel('thirds', 2), 'Groupe Y');
	assert.equal(groupLabel('thirds', 3), 'Groupe Z');
	assert.equal(groupLabel('kholles', 1), 'Groupe 01');
	assert.equal(groupLabel('kholles', 12), 'Groupe 12');
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
