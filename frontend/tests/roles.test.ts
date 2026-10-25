import assert from 'node:assert/strict';
import { test } from 'node:test';
import { roleChoice, rolesForChoice, sameRoles } from '../src/lib/roles.ts';

test('a combined role remains selected regardless of backend ordering', () => {
	assert.equal(roleChoice(['admin', 'teacher']), 'teacher_admin');
	assert.equal(roleChoice(['teacher', 'admin']), 'teacher_admin');
	assert.equal(sameRoles(['admin', 'teacher'], ['teacher', 'admin']), true);
	assert.equal(sameRoles(['admin'], ['teacher', 'admin']), false);
});

test('role choices grant only the selected capabilities and reject unknown choices', () => {
	assert.deepEqual(rolesForChoice('user'), ['user']);
	assert.deepEqual(rolesForChoice('teacher'), ['teacher']);
	assert.deepEqual(rolesForChoice('admin'), ['admin']);
	assert.deepEqual(rolesForChoice('teacher_admin'), ['teacher', 'admin']);
	assert.throws(() => rolesForChoice('unknown'));
});
