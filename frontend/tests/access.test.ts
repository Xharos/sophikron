import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canAccess } from '../src/lib/access.ts';
import type { User } from '../src/lib/types.ts';

function user(roles: string[]): User {
	return {
		id: 1,
		username: 'member',
		first_name: 'Valentin',
		last_name: 'Burgaud',
		email: null,
		status: 'active',
		roles,
		permissions: roles.flatMap(
			(role) =>
				({
					user: ['user.access'],
					kholleur: ['kholleur.access'],
					teacher: ['teacher.access', 'teaching.read'],
					admin: ['users.manage', 'users.read', 'statistics.read']
				})[role] ?? []
		),
		email_verified: false,
		is_bootstrap: false,
		created_at: '2026-10-22T12:00:00Z'
	};
}

test('anonymous visitors cannot access any account page', () => {
	for (const access of ['authenticated', 'teacher', 'admin'] as const)
		assert.equal(canAccess(null, access), false);
});

test('kholloscope requires an explicit read permission and remains admin only', () => {
	const administrator = user(['admin']);
	assert.equal(canAccess(administrator, 'kholloscope'), false);
	administrator.permissions.push('kholloscope.read');
	assert.equal(canAccess(administrator, 'kholloscope'), true);
	const teacher = user(['teacher']);
	teacher.permissions.push('kholloscope.read', 'kholloscope.write');
	assert.equal(canAccess(teacher, 'kholloscope'), false);
	administrator.is_bootstrap = true;
	assert.equal(canAccess(administrator, 'kholloscope'), false);
});

test('page permissions distinguish students, teachers and administrators', () => {
	for (const [roles, expected] of [
		[['user'], [true, false, false]],
		[['kholleur'], [true, false, false]],
		[['teacher'], [true, true, false]],
		[['admin'], [true, false, true]],
		[
			['teacher', 'admin'],
			[true, true, true]
		],
		[['custom_role'], [true, false, false]]
	] as const) {
		assert.deepEqual(
			['authenticated', 'teacher', 'admin'].map((access) =>
				canAccess(user([...roles]), access as 'authenticated' | 'teacher' | 'admin')
			),
			expected
		);
	}
});

test('role labels alone never confer a permission and bootstrap cannot access management', () => {
	const administrator = user(['admin']);
	administrator.permissions = [];
	assert.equal(canAccess(administrator, 'admin'), false);
	assert.equal(canAccess(administrator, 'staff'), false);
	const bootstrap = user(['admin']);
	bootstrap.is_bootstrap = true;
	assert.equal(canAccess(bootstrap, 'staff'), false);
	assert.equal(canAccess(user(['teacher']), 'staff'), true);
	assert.equal(canAccess(user(['kholleur']), 'staff'), true);
});
