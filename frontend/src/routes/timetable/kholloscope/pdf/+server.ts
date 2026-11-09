import type { RequestHandler } from './$types';
import { requirePageAccess } from '#lib/server/forms';
import { privatePdf } from '#lib/server/privatePdf';
import { BackendError } from '#lib/server/backend';

/** Export only a server-resolved, authorized assignment for the selected academic year. */
export const GET: RequestHandler = async (event) => {
	requirePageAccess(event, 'kholloscope');
	const year = event.url.searchParams.get('school_year') ?? '';
	if (!/^[1-9]\d{3}$/.test(year)) return new Response('Année scolaire invalide.', { status: 422 });
	try {
		const response = await privatePdf(
			event,
			`/timetable/kholloscope/${year}/pdf`,
			`kholloscope-${year}.pdf`
		);
		response.headers.set('Content-Disposition', `attachment; filename="kholloscope-${year}.pdf"`);
		return response;
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return new Response(cause.message, {
			status: cause.status,
			headers: { 'Cache-Control': 'private, no-store' }
		});
	}
};
