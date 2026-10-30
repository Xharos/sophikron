/** Relay private PDFs through server-validated fixed backend paths. */
import { isIP } from 'node:net';
import type { RequestEvent } from '@sveltejs/kit';
import { configuration } from './api.ts';
import { BackendError, relayCookies, sessionCookie } from './backend.ts';

export async function privatePdf(
	event: RequestEvent,
	path: string,
	filename: string,
	transport: typeof fetch = fetch
): Promise<Response> {
	const config = configuration();
	const address = event.getClientAddress().replace(/^::ffff:/, '');
	if (!isIP(address)) throw new BackendError(503, 'Adresse client indisponible.');
	const headers = new Headers({ accept: 'application/pdf', 'x-forwarded-for': address });
	const cookie = event.cookies.get(sessionCookie(config));
	if (cookie && /^[A-Za-z0-9_-]{1,128}$/.test(cookie))
		headers.set('cookie', `${sessionCookie(config)}=${cookie}`);
	let response: Response;
	try {
		response = await transport(`${config.backendOrigin}/api/v1${path}`, {
			headers,
			redirect: 'error',
			cache: 'no-store',
			signal: AbortSignal.any([event.request.signal, AbortSignal.timeout(60000)])
		});
	} catch {
		throw new BackendError(503, 'La génération du PDF a échoué. Réessayez.');
	}
	relayCookies(response, event.cookies, config);
	if (response.status === 401)
		event.cookies.delete(sessionCookie(config), { path: '/', secure: config.secure });
	if (!response.ok) {
		let message = 'La génération du PDF a échoué.';
		try {
			const failure = await response.json();
			if (typeof failure.detail === 'string') message = failure.detail;
		} catch {
			/* Do not expose raw infrastructure errors. */
		}
		throw new BackendError(response.status, message);
	}
	if (response.headers.get('content-type')?.split(';')[0] !== 'application/pdf')
		throw new BackendError(502, 'Le service a renvoyé un document invalide.');
	return new Response(response.body, {
		headers: {
			'Content-Type': 'application/pdf',
			'Content-Disposition': `inline; filename="${filename}"`,
			'Cache-Control': 'private, no-store',
			'X-Content-Type-Options': 'nosniff',
			'X-Robots-Tag': 'noindex, nofollow'
		}
	});
}
