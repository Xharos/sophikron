import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

/** Poll only administrator-authorized generation or group data on the same origin. */
export const GET: RequestHandler = async (event) => {
	requirePageAccess(event, 'kholloscope');
	const year = event.url.searchParams.get('school_year');
	const kind = event.url.searchParams.get('kind') ?? 'generation';
	if (!year || !/^[1-9]\d{3}$/.test(year) || !['generation', 'groups', 'revision'].includes(kind))
		return Response.json({ message: 'Demande invalide.' }, { status: 422 });
	try {
		return Response.json(await api(event, `/timetable/kholloscope/${year}/${kind}`), {
			headers: { 'Cache-Control': 'private, no-store' }
		});
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
