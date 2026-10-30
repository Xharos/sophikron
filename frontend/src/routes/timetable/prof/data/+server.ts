import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	requirePageAccess(event, 'staff');
	const query = new URLSearchParams();
	for (const key of ['school_year', 'teacher_ids', 'include_occupancy']) {
		const value = event.url.searchParams.get(key);
		if (value !== null) query.set(key, value);
	}
	try {
		return Response.json(await api(event, `/timetable/staff/board?${query}`));
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};

export const POST: RequestHandler = async (event) => {
	requirePageAccess(event, 'admin');
	const year = event.url.searchParams.get('school_year') ?? '';
	const teacher = event.url.searchParams.get('teacher_id') ?? '';
	if (!/^\d{4}$/.test(year) || !/^[1-9]\d*$/.test(teacher))
		return Response.json({ message: 'Sélection invalide.' }, { status: 422 });
	try {
		return Response.json(
			await api(
				event,
				`/timetable/staff/${year}/${teacher}/availability`,
				'PUT',
				await event.request.json()
			)
		);
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
