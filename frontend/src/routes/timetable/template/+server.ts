import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	requirePageAccess(event, 'admin');
	const year = event.url.searchParams.get('year');
	if (!year || !/^[1-9]\d*$/.test(year))
		return Response.json({ message: 'Année invalide.' }, { status: 422 });
	try {
		return Response.json(await api(event, `/timetable/years/${year}/template`));
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};

export const POST: RequestHandler = async (event) => {
	requirePageAccess(event, 'admin');
	const body: unknown = await event.request.json();
	if (
		!body ||
		typeof body !== 'object' ||
		!('year_id' in body) ||
		!Number.isSafeInteger(body.year_id) ||
		Number(body.year_id) <= 0 ||
		!('data' in body)
	)
		return Response.json({ message: 'Année invalide.' }, { status: 422 });
	try {
		return Response.json(
			await api(event, `/timetable/years/${body.year_id}/template`, 'PUT', body.data)
		);
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
