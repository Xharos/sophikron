import { configuration } from '#lib/server/api';
import type { RequestHandler } from './$types';

/** This capability endpoint never forwards browser cookies or exposes a backend origin. */
export const GET: RequestHandler = async ({ params }) => {
	const token = params.token.replace(/\.ics$/, '');
	if (!/^[A-Za-z0-9_-]{43}$/.test(token))
		return new Response('Abonnement introuvable.', { status: 404 });
	const config = configuration();
	let response: Response;
	try {
		response = await globalThis.fetch(
			`${config.backendOrigin}/api/v1/timetable/feed/${token}.ics`,
			{
				redirect: 'error',
				headers: { accept: 'text/calendar' }
			}
		);
	} catch {
		return new Response('Abonnement temporairement indisponible.', {
			status: 503,
			headers: { 'Cache-Control': 'no-store', 'Retry-After': '60' }
		});
	}
	return new Response(response.ok ? response.body : 'Abonnement indisponible.', {
		status: response.status,
		headers: {
			'Content-Type': response.ok ? 'text/calendar; charset=utf-8' : 'text/plain; charset=utf-8',
			'Cache-Control': 'private, no-store',
			'X-Robots-Tag': 'noindex, nofollow',
			'Referrer-Policy': 'no-referrer'
		}
	});
};
