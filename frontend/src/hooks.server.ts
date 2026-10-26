import type { Handle } from '@sveltejs/kit/hooks';
import { building } from '$app/env';
import { api, configuration } from '#lib/server/api';
import { BackendError, sessionCookie, validateOrigin } from '#lib/server/backend';
import type { Account } from '#lib/types';
import { themedHtml, themeCookie } from '#lib/theme';

/** Reject forged writes before making any backend request; keep identities request-scoped. */
export const handle: Handle = async ({ event, resolve }) => {
	event.locals.user = null;
	if (building) return resolve(event);
	const publicStatic = ['/sitemap.xml', '/robots.txt', '/health'].includes(event.url.pathname);
	try {
		const config =
			!publicStatic || !['GET', 'HEAD'].includes(event.request.method) ? configuration() : null;
		if (config) {
			validateOrigin(event.request, config.origin);
			if (
				!['GET', 'HEAD'].includes(event.request.method) &&
				event.url.pathname !== '/lessons/upload'
			) {
				const length = event.request.headers.get('content-length');
				if (length && (!/^\d{1,8}$/.test(length) || Number(length) > 16384))
					throw new BackendError(413, 'Demande trop volumineuse.');
				let size = 0;
				const stream = event.request.body?.pipeThrough(
					new TransformStream<Uint8Array, Uint8Array>({
						transform(chunk, controller) {
							size += chunk.byteLength;
							if (size > 16384) throw new BackendError(413, 'Demande trop volumineuse.');
							controller.enqueue(chunk);
						}
					})
				);
				if (stream)
					event = {
						...event,
						request: new Request(event.request, { body: stream, duplex: 'half' } as RequestInit)
					};
			}
			if (!publicStatic && event.cookies.get(sessionCookie(config))) {
				event.locals.user = await api<Account>(event, '/auth/me');
			}
		}
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		if (cause.status !== 401) {
			return new Response(cause.message, {
				status: cause.status,
				headers: {
					'Cache-Control': 'no-store',
					...(cause.retryAfter ? { 'Retry-After': cause.retryAfter } : {})
				}
			});
		}
	}
	const response = await resolve(event, {
		transformPageChunk: ({ html }) => themedHtml(html, event.cookies.get(themeCookie))
	});
	if (!publicStatic) {
		response.headers.set('Cache-Control', 'private, no-store');
		response.headers.set('Vary', 'Cookie');
	}
	if (event.url.pathname !== '/') response.headers.set('X-Robots-Tag', 'noindex, nofollow');
	response.headers.set('X-Content-Type-Options', 'nosniff');
	// Native POST forms must retain their origin for SvelteKit's CSRF protection.
	response.headers.set('Referrer-Policy', 'same-origin');
	response.headers.set('X-Frame-Options', 'DENY');
	return response;
};
