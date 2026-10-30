import assert from 'node:assert/strict';
import { test } from 'node:test';
import { promotionCandidates } from '../src/lib/dashboard.ts';
import type { DirectoryUser } from '../src/lib/types.ts';
import {
	canJoinPromotion,
	roleSelectionError,
	roleOptions,
	sameRoles,
	teachingRoleEntries
} from '../src/lib/roles.ts';

test('staff roles combine independently and ordering does not change grants', () => {
	assert.equal(sameRoles(['admin', 'teacher'], ['teacher', 'admin']), true);
	assert.equal(sameRoles(['admin'], ['teacher', 'admin']), false);
	for (let mask = 1; mask < 8; mask++) {
		const roles = ['kholleur', 'teacher', 'admin'].filter((_, index) => mask & (1 << index));
		assert.equal(roleSelectionError(roles), '');
	}
	assert.equal(roleSelectionError(['user']), '');
	assert.equal(new Set(roleOptions.map((option) => option.value)).size, 4);
});
test('pupil exclusivity, a nonempty selection and known unique roles are required on save', () => {
	for (const roles of [
		[],
		['unknown'],
		['admin', 'admin'],
		['user', 'kholleur'],
		['user', 'teacher'],
		['user', 'admin'],
		['user', 'teacher', 'admin']
	])
		assert.notEqual(roleSelectionError(roles), '');
});

test('subject staff appear once for each teaching role, with contextual badges and sorted names', () => {
	const members = [
		{ id: 1, first_name: 'Val', last_name: 'Zulu', roles: ['admin', 'teacher'] },
		{ id: 2, first_name: 'Zoé', last_name: 'Éclair', roles: ['teacher', 'kholleur', 'admin'] },
		{ id: 3, first_name: 'Alice', last_name: 'Alpha', roles: ['kholleur'] },
		{ id: 4, first_name: 'Bob', last_name: 'Eclair', roles: ['teacher'] },
		{ id: 5, first_name: 'Sam', last_name: 'Admin', roles: ['admin'] }
	];
	assert.deepEqual(
		teachingRoleEntries(members).map(({ member, role }) => [member.id, role]),
		[
			[4, 'teacher'],
			[2, 'teacher'],
			[1, 'teacher'],
			[3, 'kholleur'],
			[2, 'kholleur']
		]
	);
	assert.deepEqual(
		members.map((member) => member.id),
		[1, 2, 3, 4, 5]
	);
	assert.deepEqual(teachingRoleEntries([]), []);
	assert.deepEqual(teachingRoleEntries([members[4]]), []);
});

test('promotion eligibility checks independent roles rather than the highest role', () => {
	for (const roles of [
		['user'],
		['teacher'],
		['kholleur'],
		['admin', 'teacher'],
		['admin', 'kholleur'],
		['admin', 'teacher', 'kholleur']
	])
		assert.equal(canJoinPromotion(roles), true);
	for (const roles of [[], ['admin'], ['unknown']]) assert.equal(canJoinPromotion(roles), false);
});

test('promotion teaching candidates use one server union filter for listing and search', async (t) => {
	const candidates: DirectoryUser[] = [
		{
			id: 1,
			roles: ['teacher'],
			username: 'teacher',
			first_name: 'Camille',
			last_name: 'Martin',
			status: 'active'
		},
		{
			id: 2,
			roles: ['kholleur'],
			username: 'kholleur',
			first_name: 'Camille',
			last_name: 'Martin',
			status: 'active'
		},
		{
			id: 3,
			roles: ['admin', 'teacher', 'kholleur'],
			username: 'both',
			first_name: 'Camille',
			last_name: 'Martin',
			status: 'active'
		}
	];
	const requests: URL[] = [];
	const controller = new AbortController();
	t.mock.method(globalThis, 'fetch', async (input: string, options: RequestInit) => {
		const url = new URL(input, 'http://localhost');
		requests.push(url);
		assert.equal(options.signal, controller.signal);
		assert.equal(url.searchParams.get('role'), 'teaching');
		assert.equal(url.searchParams.get('limit'), '20');
		return Response.json(
			url.searchParams.get('resource') === 'users' ? { items: candidates } : candidates
		);
	});
	for (const query of ['', '  Camille  '])
		assert.deepEqual(await promotionCandidates('teaching', query, controller.signal), candidates);
	assert.equal(requests.length, 2);
	assert.deepEqual(
		requests.map((url) => url.searchParams.get('resource')),
		['users', 'search']
	);
	assert.equal(requests[1].searchParams.get('q'), 'Camille');
});

test('promotion pupil category requests only pupils and waits for two search characters', async (t) => {
	const requests: URL[] = [];
	t.mock.method(globalThis, 'fetch', async (input: string) => {
		const url = new URL(input, 'http://localhost');
		requests.push(url);
		assert.equal(url.searchParams.get('role'), 'user');
		return Response.json(url.searchParams.get('resource') === 'users' ? { items: [] } : []);
	});
	assert.deepEqual(await promotionCandidates('teaching', ' C '), []);
	assert.deepEqual(await promotionCandidates('user', 'C'), []);
	assert.equal(requests.length, 0);
	await promotionCandidates('user', '');
	await promotionCandidates('user', 'Camille');
	assert.equal(requests.length, 2);
});

test('promotion candidates propagate request failures and cancellation without partial results', async (t) => {
	for (const status of [403, 500]) {
		t.mock.method(globalThis, 'fetch', async () =>
			Response.json({ message: 'Recherche indisponible' }, { status })
		);
		await assert.rejects(promotionCandidates('teaching', ''), /Recherche indisponible/);
	}
	const controller = new AbortController();
	controller.abort();
	t.mock.method(globalThis, 'fetch', async (_input: string, options: RequestInit) => {
		options.signal?.throwIfAborted();
		return Response.json({ items: [] });
	});
	await assert.rejects(promotionCandidates('teaching', '', controller.signal), {
		name: 'AbortError'
	});
});

test('both promotion candidate categories exclude existing members in listing and search', async (t) => {
	const requests: URL[] = [];
	t.mock.method(globalThis, 'fetch', async (input: string) => {
		const url = new URL(input, 'http://localhost');
		requests.push(url);
		assert.equal(url.searchParams.get('exclude_promotion_id'), '42');
		assert.equal(url.searchParams.get('limit'), '20');
		return Response.json(url.searchParams.get('resource') === 'users' ? { items: [] } : []);
	});
	for (const category of ['user', 'teaching'] as const) {
		for (const query of ['', 'Camille']) {
			await promotionCandidates(category, query, undefined, 42);
			assert.equal(requests.at(-1)?.searchParams.get('role'), category);
		}
	}
	assert.equal(requests.length, 4);
});
