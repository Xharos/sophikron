import type { Handle } from '@sveltejs/kit/hooks';
import { building } from '$app/env';
import { api, configuration } from '#lib/server/api';
import { BackendError, sessionCookie, validateOrigin } from '#lib/server/backend';
import type { Account } from '#lib/types';

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
	const response = await resolve(event);
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
