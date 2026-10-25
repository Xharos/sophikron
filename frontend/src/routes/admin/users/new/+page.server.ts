import { redirect } from '@sveltejs/kit';
import { requireUser } from '#lib/server/forms';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = (event) => {
	requireUser(event, true);
	redirect(303, '/dashboard?tab=accounts&create=account');
};
