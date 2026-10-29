/** Relay private roster PDFs through a fixed, authenticated backend endpoint. */
import { isIP } from 'node:net';
import type { RequestEvent } from '@sveltejs/kit';
import { hasPermission } from '../access.ts';
import { configuration } from './api.ts';
import { BackendError, relayCookies, sessionCookie } from './backend.ts';

export async function promotionAttendance(
	event: RequestEvent,
	transport: typeof fetch = fetch
): Promise<Response> {
	if (!event.locals.user) throw new BackendError(401, 'Votre session a expiré.');
	if (
		!['users.read', 'teaching.read'].some((permission) =>
			hasPermission(event.locals.user, permission)
		)
	)
		throw new BackendError(403, 'Vous n’avez pas accès à cette action.');
	const value = event.url.searchParams.get('promotionId');
	const promotionId = Number(value);
	if (!value || !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(promotionId))
		throw new BackendError(422, 'Promotion invalide.');
	const config = configuration();
	const address = event.getClientAddress().replace(/^::ffff:/, '');
	if (!isIP(address)) throw new BackendError(503, 'Adresse client indisponible.');
	const headers = new Headers({ accept: 'application/pdf', 'x-forwarded-for': address });
	const cookie = event.cookies.get(sessionCookie(config));
	if (cookie && /^[A-Za-z0-9_-]{1,128}$/.test(cookie))
		headers.set('cookie', `${sessionCookie(config)}=${cookie}`);
	let response: Response;
	try {
		response = await transport(
			`${config.backendOrigin}/api/v1/promotion-groups/${promotionId}/attendance`,
			{
				headers,
				redirect: 'error',
				cache: 'no-store',
				signal: AbortSignal.any([event.request.signal, AbortSignal.timeout(60000)])
			}
		);
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
			'Content-Disposition': `inline; filename="presence-promotion-${promotionId}.pdf"`,
			'Cache-Control': 'private, no-store',
			'X-Content-Type-Options': 'nosniff',
			'X-Robots-Tag': 'noindex, nofollow'
		}
	});
}
