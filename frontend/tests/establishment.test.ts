import assert from 'node:assert/strict';
import { test } from 'node:test';
import { load } from '../src/routes/+layout.server.ts';

test('the root layout reads the establishment name at runtime and preserves session data', async () => {
	const previousName = process.env.ESTABLISHMENT_NAME;
	const previousOrigin = process.env.ORIGIN;
	const locals = { user: null };
	const event = { locals } as Parameters<typeof load>[0];
	try {
		process.env.ORIGIN = 'https://school.example';
		for (const [configured, expected] of [
			[undefined, 'Sophikron'],
			['', 'Sophikron'],
			[' \t ', 'Sophikron'],
			['Sophikron', 'Sophikron'],
			['  Lycée Jean Moulin  ', 'Lycée Jean Moulin'],
			['École d’Art & "Sciences" <test>', 'École d’Art & "Sciences" <test>']
		]) {
			if (configured === undefined) delete process.env.ESTABLISHMENT_NAME;
			else process.env.ESTABLISHMENT_NAME = configured;
			assert.deepEqual(await load(event), {
				user: locals.user,
				siteOrigin: 'https://school.example',
				establishmentName: expected
			});
		}
	} finally {
		if (previousName === undefined) delete process.env.ESTABLISHMENT_NAME;
		else process.env.ESTABLISHMENT_NAME = previousName;
		if (previousOrigin === undefined) delete process.env.ORIGIN;
		else process.env.ORIGIN = previousOrigin;
	}
});
