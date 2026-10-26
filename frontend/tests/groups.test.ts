import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupError, groupLabel, moveStudent } from '../src/lib/groups.ts';

test('partition names distinguish letters from padded khôlle numbers', () => {
	assert.equal(groupLabel('halves', 1), 'Groupe A');
	assert.equal(groupLabel('thirds', 3), 'Groupe C');
	assert.equal(groupLabel('kholles', 1), 'Groupe 01');
	assert.equal(groupLabel('kholles', 12), 'Groupe 12');
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
