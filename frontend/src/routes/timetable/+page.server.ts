import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { error } from '@sveltejs/kit';
import type { TimetableCatalog } from '#lib/timetable';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event, 'staff');
	try {
		return { catalog: await api<TimetableCatalog>(event, '/timetable/catalog') };
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
