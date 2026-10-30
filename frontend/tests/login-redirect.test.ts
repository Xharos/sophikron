import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loginDestination, safeReturnTo } from '../src/lib/loginRedirect.ts';

test('login retains local paths, queries and content anchors', () => {
	const destination = '/dashboard/user?id=3#roles';
	assert.equal(safeReturnTo(destination), destination);
	assert.equal(
		new URL(loginDestination(destination), 'https://school.test').searchParams.get('next'),
		destination
	);
});

test('login rejects external, ambiguous and cyclic return destinations', () => {
	for (const value of [
		null,
		'',
		'https://evil.test/',
		'//evil.test/',
		'/\\evil.test',
		'/%2f%2fevil.test',
		'/%5cevil.test',
		'/%00test',
		'/login',
		'/a/../login?next=/',
		'/logout',
		'/%6cogin',
		'/bad%'
	])
		assert.equal(safeReturnTo(value), '/');
	assert.equal(
		safeReturnTo('/lessons/3?q=https%3A%2F%2Fexample.test'),
		'/lessons/3?q=https%3A%2F%2Fexample.test'
	);
});
