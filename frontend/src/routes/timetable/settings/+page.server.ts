import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { error } from '@sveltejs/kit';
import type { CommonTimetableYear } from '#lib/timetable';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event, 'admin');
	try {
		return {
			configuration: await api<{
				today: string;
				preferences: { auto_archive: boolean; revision: string };
				years: CommonTimetableYear[];
				rooms: { id: number; name: string; revision: string }[];
			}>(event, '/timetable/configuration')
		};
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
