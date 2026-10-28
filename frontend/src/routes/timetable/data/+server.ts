import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	requirePageAccess(event, 'staff');
	const query = new URLSearchParams();
	for (const name of ['calendar_ids', 'school_year', 'draft']) {
		const value = event.url.searchParams.get(name);
		if (value !== null) query.set(name, value);
	}
	try {
		return Response.json(await api(event, `/timetable/board?${query}`));
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
