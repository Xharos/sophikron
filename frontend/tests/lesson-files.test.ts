import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import type { RequestEvent } from '@sveltejs/kit';
import { transferLessonFile } from '../src/lib/server/lessonFiles.ts';

process.env.ORIGIN = 'https://school.example';
process.env.BACKEND_ORIGIN = 'http://internal.example';

function event(upload: boolean, query?: string) {
	const changes: string[] = [];
	const url = new URL(
		`https://school.example/lessons/${upload ? 'upload' : 'download'}?${query ?? (upload ? `lessonId=12&uploadId=${'a'.repeat(32)}` : 'lessonId=12&fileId=34')}`
	);
	const request = new Request(
		url,
		upload
			? {
					method: 'POST',
					headers: {
						origin: 'https://school.example',
						'content-type': 'application/octet-stream',
						'x-forwarded-for': '1.2.3.4',
						cookie: 'unrelated=secret'
					},
					body: 'binary content'
				}
			: {}
	);
	const input = {
		url,
		request,
		locals: { user: { is_bootstrap: false } },
		getClientAddress: () => '203.0.113.5',
		cookies: {
			get: (name: string) => (name === '__Host-sophikron_session' ? 'test_session' : undefined),
			delete: (name: string) => changes.push(name)
		}
	} as unknown as RequestEvent;
	return { input, changes };
}

test('binary upload streams bytes to a fixed backend path and replaces untrusted headers', async () => {
	const { input } = event(true);
	const response = await transferLessonFile(input, true, async (url, options) => {
		assert.equal(url, `http://internal.example/api/v1/lessons/12/uploads/${'a'.repeat(32)}`);
		assert.equal(options?.method, 'PUT');
		const headers = new Headers(options?.headers);
		assert.equal(headers.get('cookie'), '__Host-sophikron_session=test_session');
		assert.equal(headers.get('x-forwarded-for'), '203.0.113.5');
		assert.equal(headers.get('x-csrf-protection'), '1');
		assert.equal(headers.get('origin'), 'https://school.example');
		assert.equal(await new Response(options?.body).text(), 'binary content');
		return Response.json({ version: 2 });
	});
	assert.deepEqual(await response.json(), { version: 2 });
});

test('downloads preserve bytes, safe attachment headers and private caching', async () => {
	const { input } = event(false);
	const response = await transferLessonFile(input, false, async (url, options) => {
		assert.equal(url, 'http://internal.example/api/v1/lessons/12/files/34');
		assert.equal(options?.method, 'GET');
		assert.equal(options?.signal, input.request.signal);
		return new Response(new Uint8Array([0, 255, 128]), {
			headers: {
				'content-disposition': 'attachment; filename="example.pdf"',
				'content-type': 'application/pdf',
				'content-length': '3',
				'x-private-diagnostic': 'never relay'
			}
		});
	});
	assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [0, 255, 128]);
	assert.match(response.headers.get('content-disposition') ?? '', /attachment/);
	assert.equal(response.headers.get('cache-control'), 'private, no-store');
	assert.equal(response.headers.get('x-private-diagnostic'), null);
});

test('binary bridge rejects forged origins, bad identifiers and oversized declarations before network IO', async () => {
	for (const scenario of ['origin', 'identifier', 'size', 'session']) {
		const { input } = event(
			true,
			scenario === 'identifier' ? 'lessonId=12&uploadId=../admin' : undefined
		);
		if (scenario === 'origin') input.request.headers.set('origin', 'https://evil.example');
		if (scenario === 'size') input.request.headers.set('content-length', '52428801');
		if (scenario === 'session') input.locals.user = null;
		let calls = 0;
		await assert.rejects(
			transferLessonFile(input, true, async () => {
				calls++;
				return new Response();
			}),
			{
				status:
					scenario === 'origin'
						? 403
						: scenario === 'identifier'
							? 422
							: scenario === 'size'
								? 413
								: 401
			}
		);
		assert.equal(calls, 0);
	}
});

test('expired download sessions clear the cookie and keep backend denial', async () => {
	const { input, changes } = event(false);
	await assert.rejects(
		transferLessonFile(input, false, async () =>
			Response.json({ detail: 'Session expired' }, { status: 401 })
		),
		{ status: 401 }
	);
	assert.deepEqual(changes, ['__Host-sophikron_session']);
});

test('binary bridge exchanges a streamed upload with a real HTTP service', async () => {
	const previousOrigin = process.env.BACKEND_ORIGIN;
	const server = createServer(async (request, response) => {
		const chunks: Buffer[] = [];
		for await (const chunk of request) chunks.push(Buffer.from(chunk));
		assert.equal(Buffer.concat(chunks).toString(), 'binary content');
		assert.equal(request.headers['content-type'], 'application/octet-stream');
		assert.equal(request.headers.cookie, '__Host-sophikron_session=test_session');
		response.setHeader('content-type', 'application/json');
		response.end(JSON.stringify({ version: 3 }));
	});
	await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
	try {
		process.env.BACKEND_ORIGIN = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
		const response = await transferLessonFile(event(true).input, true);
		assert.deepEqual(await response.json(), { version: 3 });
	} finally {
		process.env.BACKEND_ORIGIN = previousOrigin;
		await new Promise<void>((resolve, reject) =>
			server.close((error) => (error ? reject(error) : resolve()))
		);
	}
});
