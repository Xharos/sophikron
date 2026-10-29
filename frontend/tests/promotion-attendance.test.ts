import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { RequestEvent } from '@sveltejs/kit';
import { promotionAttendance } from '../src/lib/server/promotionAttendance.ts';

process.env.ORIGIN = 'https://school.example';
process.env.BACKEND_ORIGIN = 'http://internal.example';

function event(permissions: string[] = ['teaching.read'], query = 'promotionId=12') {
	const deleted: string[] = [];
	const url = new URL(`https://school.example/dashboard/attendance?${query}`);
	const input = {
		url,
		request: new Request(url, {
			headers: { cookie: 'unrelated=secret', 'x-forwarded-for': '1.2.3.4' }
		}),
		locals: { user: { is_bootstrap: false, permissions } },
		getClientAddress: () => '203.0.113.5',
		cookies: {
			get: (name: string) => (name === '__Host-sophikron_session' ? 'test_session' : undefined),
			delete: (name: string) => deleted.push(name)
		}
	} as unknown as RequestEvent;
	return { input, deleted };
}

test('attendance PDF relays only a fixed authenticated route and safe inline headers', async () => {
	const { input } = event();
	const response = await promotionAttendance(input, async (url, options) => {
		assert.equal(url, 'http://internal.example/api/v1/promotion-groups/12/attendance');
		const headers = new Headers(options?.headers);
		assert.equal(headers.get('cookie'), '__Host-sophikron_session=test_session');
		assert.equal(headers.get('x-forwarded-for'), '203.0.113.5');
		assert.equal(headers.get('accept'), 'application/pdf');
		assert.equal(options?.cache, 'no-store');
		return new Response('%PDF-synthetic', {
			headers: {
				'content-type': 'application/pdf',
				'content-disposition': 'attachment; filename="untrusted"',
				'x-private-diagnostic': 'never relay'
			}
		});
	});
	assert.equal(await response.text(), '%PDF-synthetic');
	assert.equal(
		response.headers.get('content-disposition'),
		'inline; filename="presence-promotion-12.pdf"'
	);
	assert.equal(response.headers.get('cache-control'), 'private, no-store');
	assert.equal(response.headers.get('x-private-diagnostic'), null);
	assert.equal(response.headers.get('x-robots-tag'), 'noindex, nofollow');
});

test('attendance refuses anonymous, bootstrap and pupil requests before fetching', async () => {
	for (const scenario of ['anonymous', 'bootstrap', 'pupil', 'kholleur']) {
		const { input } = event(scenario === 'kholleur' ? ['kholleur.access'] : []);
		if (scenario === 'anonymous') input.locals.user = null;
		if (scenario === 'bootstrap') input.locals.user!.is_bootstrap = true;
		await assert.rejects(
			promotionAttendance(input, async () => {
				assert.fail('An unauthorized request must never reach the backend');
			}),
			{ status: scenario === 'anonymous' ? 401 : 403 }
		);
	}
});

test('attendance validates identifiers and retains backend scope or session denials', async () => {
	for (const value of ['', '-1', '0', '1.5', '../admin', '9007199254740992']) {
		await assert.rejects(
			promotionAttendance(event(['users.read'], `promotionId=${value}`).input, async () => {
				assert.fail('Invalid identifier reached the backend');
			}),
			{ status: 422 }
		);
	}
	for (const status of [401, 403, 404]) {
		const { input, deleted } = event();
		await assert.rejects(
			promotionAttendance(input, async () => Response.json({ detail: 'Denied' }, { status })),
			{ status }
		);
		assert.equal(deleted.length, status === 401 ? 1 : 0);
	}
});

test('attendance does not display a non-PDF response as a document', async () => {
	await assert.rejects(
		promotionAttendance(event().input, async () => Response.json({ message: 'wrong type' })),
		{ status: 502 }
	);
});
