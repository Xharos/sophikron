import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { error } from '@sveltejs/kit';
import type { TimetableCatalog } from '#lib/timetable';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event, 'staff');
	try {
		const catalog = await api<TimetableCatalog>(event, '/timetable/catalog');
		const agenda = catalog.calendars.find((item) => item.id === Number(event.params.id));
		if (!agenda) error(404, 'Agenda introuvable.');
		return { catalog, agenda };
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
