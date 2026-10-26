/** Binary BFF with fixed routes, bounded upload streams and session-only credentials. */
import { isIP } from 'node:net';
import type { RequestEvent } from '@sveltejs/kit';
import { configuration } from './api.ts';
import { BackendError, relayCookies, sessionCookie, validateOrigin } from './backend.ts';
import { lessonIdentifier, requireLessonSession } from './lessons.ts';

export async function transferLessonFile(
	event: RequestEvent,
	upload: boolean,
	transport: typeof fetch = fetch
): Promise<Response> {
	requireLessonSession(event);
	const config = configuration();
	validateOrigin(event.request, config.origin);
	const lessonId = lessonIdentifier(event.url.searchParams.get('lessonId'));
	const id = event.url.searchParams.get(upload ? 'uploadId' : 'fileId');
	if (upload && (!id || !/^[0-9a-f]{32}$/.test(id))) throw new BackendError(422, 'Dépôt invalide.');
	const path = upload ? `uploads/${id}` : `files/${lessonIdentifier(id)}`;
	const address = event.getClientAddress().replace(/^::ffff:/, '');
	if (!isIP(address)) throw new BackendError(503, 'Adresse client indisponible.');
	const headers = new Headers({ 'x-forwarded-for': address });
	const cookie = event.cookies.get(sessionCookie(config));
	if (cookie && /^[A-Za-z0-9_-]{1,128}$/.test(cookie))
		headers.set('cookie', `${sessionCookie(config)}=${cookie}`);
	let body: ReadableStream<Uint8Array> | undefined;
	if (upload) {
		if (event.request.headers.get('content-type') !== 'application/octet-stream')
			throw new BackendError(415, 'Format de transfert invalide.');
		headers.set('origin', config.origin);
		headers.set('x-csrf-protection', '1');
		headers.set('content-type', 'application/octet-stream');
		const length = event.request.headers.get('content-length');
		if (length && (!/^\d{1,9}$/.test(length) || Number(length) > 52428800))
			throw new BackendError(413, 'Fichier trop volumineux.');
		let size = 0;
		body = event.request.body?.pipeThrough(
			new TransformStream<Uint8Array, Uint8Array>({
				transform(chunk, controller) {
					size += chunk.byteLength;
					if (size > 52428800) throw new BackendError(413, 'Fichier trop volumineux.');
					controller.enqueue(chunk);
				}
			})
		);
	}
	let response: Response;
	try {
		response = await transport(`${config.backendOrigin}/api/v1/lessons/${lessonId}/${path}`, {
			method: upload ? 'PUT' : 'GET',
			headers,
			body,
			redirect: 'error',
			cache: 'no-store',
			// Downloads can wait for a global backend slot; browser cancellation still propagates.
			signal: upload
				? AbortSignal.any([event.request.signal, AbortSignal.timeout(360000)])
				: event.request.signal,
			...(upload ? { duplex: 'half' } : {})
		} as RequestInit);
	} catch {
		throw new BackendError(
			503,
			'Le transfert a été interrompu. Actualisez le cours avant de réessayer.'
		);
	}
	relayCookies(response, event.cookies, config);
	if (response.status === 401)
		event.cookies.delete(sessionCookie(config), { path: '/', secure: config.secure });
	if (!response.ok) {
		let message = 'Le transfert du document a échoué.';
		try {
			const data = await response.json();
			if (typeof data.detail === 'string') message = data.detail;
		} catch {
			/* Infrastructure responses may not be JSON. */
		}
		throw new BackendError(response.status, message);
	}
	const output = new Headers({
		'Cache-Control': 'private, no-store',
		'X-Content-Type-Options': 'nosniff',
		'X-Robots-Tag': 'noindex, nofollow'
	});
	for (const name of ['content-type', 'content-length', 'content-disposition']) {
		const value = response.headers.get(name);
		if (value) output.set(name, value);
	}
	return new Response(response.body, { status: response.status, headers: output });
}
