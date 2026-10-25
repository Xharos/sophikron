import { requirePageAccess } from '#lib/server/forms';
import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = (event) => {
	requirePageAccess(event, 'admin');
	redirect(303, '/dashboard');
};
