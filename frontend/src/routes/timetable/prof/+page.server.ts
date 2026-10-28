import { error } from '@sveltejs/kit';
import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { TeacherCatalog } from '#lib/teacherTimetable';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event, 'staff');
	try {
		return { catalog: await api<TeacherCatalog>(event, '/timetable/staff/catalog') };
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
