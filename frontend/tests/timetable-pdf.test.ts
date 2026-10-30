import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { RequestEvent } from '@sveltejs/kit';
import { timetablePdf } from '../src/lib/server/timetablePdf.ts';

process.env.ORIGIN = 'https://school.example';
process.env.BACKEND_ORIGIN = 'http://internal.example';

function event(query = 'year_id=2&day=2026-11-02&node=halves-1', permissions = ['teaching.read']) {
	const url = new URL(`https://school.example/timetable/12/pdf?${query}`);
	return {
		url,
		params: { id: '12' },
		request: new Request(url),
		locals: { user: { permissions, is_bootstrap: false } },
		getClientAddress: () => '203.0.113.5',
		cookies: { get: () => 'test_session', delete: () => {} }
	} as unknown as RequestEvent;
}

test('timetable export relays selected week and audience privately to a fixed route', async () => {
	const response = await timetablePdf(event(), async (url, options) => {
		assert.equal(
			url,
			'http://internal.example/api/v1/timetable/calendars/12/pdf?year_id=2&day=2026-11-02&node=halves-1'
		);
		assert.equal(
			new Headers(options?.headers).get('cookie'),
			'__Host-sophikron_session=test_session'
		);
		assert.equal(options?.cache, 'no-store');
		return new Response('%PDF-test', { headers: { 'content-type': 'application/pdf' } });
	});
	assert.equal(response.headers.get('cache-control'), 'private, no-store');
	assert.equal(response.headers.get('x-robots-tag'), 'noindex, nofollow');
});

test('timetable export rejects malformed views, anonymous users and unauthorized roles', async () => {
	const never = async () => {
		throw new Error('Must not fetch');
	};
	for (const query of [
		'year_id=2&day=2026-02-30',
		'year_id=2&day=2026-11-02&node=../secret',
		'year_id=0&day=2026-11-02'
	])
		await assert.rejects(timetablePdf(event(query), never), { status: 422 });
	await assert.rejects(timetablePdf(event(undefined, []), never), { status: 403 });
	const anonymous = event();
	anonymous.locals.user = null;
	await assert.rejects(timetablePdf(anonymous, never), { status: 401 });
	await assert.rejects(
		timetablePdf(event(), async () =>
			Response.json({ detail: 'Agenda introuvable.' }, { status: 404 })
		),
		{ status: 404 }
	);
});
