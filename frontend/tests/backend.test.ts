import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { Cookies } from '@sveltejs/kit';
import {
	BackendError,
	relayCookies,
	requestBackend,
	validateOrigin,
	type BackendEvent
} from '#lib/server/backend.ts';

const config = {
	origin: 'https://school.example',
	backendOrigin: 'http://backend:8000',
	secure: true
};

test('the bridge permits course roots and element operations while refusing arbitrary service paths', async () => {
	for (const [path, method] of [
		['/lessons?q=maths', 'GET'],
		['/lessons', 'POST'],
		['/lessons/12', 'PUT'],
		['/lessons/12/elements/34', 'DELETE'],
		['/lessons/12/elements/34/move', 'POST'],
		['/lessons/12/promotion-options?offset=0', 'GET']
	] as const) {
		await requestBackend(event().input, config, path, method, undefined, async (url) => {
			assert.equal(url, `${config.backendOrigin}/api/v1${path}`);
			return Response.json({ success: true });
		});
	}
	for (const path of [
		'/lessons/../admin/users',
		'//evil.example',
		'/lessons/12#secret',
		'/unknown/path'
	]) {
		let called = false;
		await assert.rejects(
			requestBackend(event().input, config, path, 'GET', undefined, async () => {
				called = true;
				return Response.json({});
			}),
			{ status: 500 }
		);
		assert.equal(called, false);
	}
});
function event(origin: string | null = config.origin, method = 'POST') {
	const changes: { name: string; value?: string; options: Record<string, unknown> }[] = [];
	const values = new Map([
		['__Host-sophikron_session', 'opaque_test_session'],
		['unrelated', 'private']
	]);
	const cookies = {
		get: (name: string) => values.get(name),
		set: (name: string, value: string, options: Record<string, unknown>) => {
			changes.push({ name, value, options });
		},
		delete: (name: string, options: Record<string, unknown>) => {
			changes.push({ name, options });
		}
	} as unknown as Cookies;
	const headers = new Headers({ 'x-forwarded-for': '1.2.3.4', 'x-real-ip': '5.6.7.8' });
	if (origin) headers.set('origin', origin);
	const input: BackendEvent = {
		request: new Request(`${config.origin}/login`, { method, headers }),
		cookies,
		getClientAddress: () => '203.0.113.7'
	};
	return { input, changes };
}

test('reject missing, null and foreign origins before adding trusted backend headers', async () => {
	for (const origin of [null, 'null', 'https://evil.example', 'https://school.example.evil']) {
		let calls = 0;
		await assert.rejects(
			requestBackend(event(origin).input, config, '/auth/login', 'POST', {}, async () => {
				calls++;
				return new Response();
			}),
			{ status: 403 }
		);
		assert.equal(calls, 0);
	}
	assert.doesNotThrow(() => validateOrigin(event(null, 'GET').input.request, config.origin));
});

test('replace forged forwarding headers, forward only the session cookie, preserve JSON and CSRF', async () => {
	const { input } = event();
	await requestBackend(
		input,
		config,
		'/auth/login',
		'POST',
		{ identifier: 'member', password: 'not-logged' },
		async (url, init) => {
			assert.equal(url, 'http://backend:8000/api/v1/auth/login');
			const headers = new Headers(init?.headers);
			assert.equal(headers.get('x-forwarded-for'), '203.0.113.7');
			assert.equal(headers.get('x-real-ip'), null);
			assert.equal(headers.get('origin'), config.origin);
			assert.equal(headers.get('x-csrf-protection'), '1');
			assert.equal(headers.get('cookie'), '__Host-sophikron_session=opaque_test_session');
			assert.equal(headers.get('content-type'), 'application/json');
			assert.equal(init?.redirect, 'error');
			return new Response(null, { status: 204 });
		}
	);
});

test('relay HttpOnly cookie creation and deletion with the same host-only scope', () => {
	const { input, changes } = event();
	for (const cookie of [
		'__Host-sophikron_session=new_session; HttpOnly; Secure; SameSite=lax; Path=/; Max-Age=28800',
		'__Host-sophikron_session=""; HttpOnly; Secure; SameSite=lax; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT'
	])
		relayCookies(new Response(null, { headers: { 'set-cookie': cookie } }), input.cookies, config);
	assert.equal(changes.length, 2);
	assert.equal(changes[0].value, 'new_session');
	assert.equal(changes[0].options.httpOnly, true);
	assert.equal(changes[0].options.secure, true);
	assert.equal(changes[1].options.maxAge, 0);
	assert.equal(changes[1].options.path, '/');
	assert.equal(changes[0].options.domain, undefined);
});

test('reject weakened session cookies and ignore unrelated cookies', () => {
	const { input, changes } = event();
	for (const attributes of [
		'Path=/; SameSite=lax; Secure',
		'Path=/; SameSite=lax; HttpOnly',
		'Path=/; SameSite=lax; HttpOnly; Secure; Domain=school.example'
	]) {
		assert.throws(
			() =>
				relayCookies(
					new Response(null, {
						headers: { 'set-cookie': `__Host-sophikron_session=x; ${attributes}` }
					}),
					input.cookies,
					config
				),
			BackendError
		);
	}
	relayCookies(new Response(null, { headers: { 'set-cookie': 'other=x' } }), input.cookies, config);
	assert.equal(changes.length, 0);
});

test('expired sessions clear the browser cookie and keep HTTP 401', async () => {
	const { input, changes } = event();
	await assert.rejects(
		requestBackend(input, config, '/auth/me', 'GET', undefined, async () =>
			Response.json({ detail: 'Session expirée.' }, { status: 401 })
		),
		{ status: 401 }
	);
	assert.equal(changes[0].name, '__Host-sophikron_session');
	assert.equal(changes[0].value, undefined);
});

test('preserve rate limiting and Retry-After without echoing credentials', async () => {
	await assert.rejects(
		requestBackend(event().input, config, '/auth/login', 'POST', {}, async () =>
			Response.json(
				{ detail: 'Réessayez plus tard.' },
				{ status: 429, headers: { 'Retry-After': '42' } }
			)
		),
		{ status: 429, retryAfter: '42' }
	);
	await assert.rejects(
		requestBackend(event().input, config, '/auth/login', 'POST', {}, async () => {
			throw new Error('secret internal diagnostic');
		}),
		(cause: unknown) =>
			cause instanceof BackendError && cause.status === 503 && !cause.message.includes('secret')
	);
});

test('bridge exchanges real HTTP with an internal service', async () => {
	const server = createServer((request, response) => {
		assert.equal(request.headers['x-forwarded-for'], '203.0.113.7');
		response.writeHead(200, {
			'content-type': 'application/json',
			'set-cookie':
				'__Host-sophikron_session=http_session; HttpOnly; Secure; SameSite=lax; Path=/; Max-Age=60'
		});
		response.end('{"roles":["user"]}');
	});
	await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
	try {
		const { input, changes } = event();
		const port = (server.address() as AddressInfo).port;
		const result = await requestBackend<{ roles: string[] }>(
			input,
			{ ...config, backendOrigin: `http://127.0.0.1:${port}` },
			'/auth/login',
			'POST',
			{}
		);
		assert.deepEqual(result.roles, ['user']);
		assert.equal(changes[0].value, 'http_session');
	} finally {
		await new Promise<void>((resolve, reject) =>
			server.close((error) => (error ? reject(error) : resolve()))
		);
	}
});

test('bridge supports typed mutations and encoded directory queries without permitting GET writes', async () => {
	for (const method of ['PATCH', 'PUT', 'DELETE'] as const) {
		await requestBackend(
			event().input,
			config,
			'/admin/users/1/archive',
			method,
			{ archived: true },
			async (_url, init) => {
				assert.equal(init?.method, method);
				assert.equal(new Headers(init?.headers).get('x-csrf-protection'), '1');
				return new Response(null, { status: 204 });
			}
		);
		await assert.rejects(
			requestBackend(event(null, 'GET').input, config, '/admin/users/1/archive', method),
			{ status: 405 }
		);
	}
	await requestBackend(
		event(null, 'GET').input,
		config,
		'/teaching/users/search?q=du%20sejour&limit=20',
		'GET',
		undefined,
		async (url) => {
			assert.equal(url, 'http://backend:8000/api/v1/teaching/users/search?q=du%20sejour&limit=20');
			return Response.json([]);
		}
	);
	for (const path of [
		'https://evil.example',
		'/admin/../auth/setup',
		'//evil.example/admin/users',
		'/admin/users#private'
	]) {
		await assert.rejects(requestBackend(event(null, 'GET').input, config, path), { status: 500 });
	}
});
