import { requirePageAccess } from '#lib/server/forms';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = (event) => {
	requirePageAccess(event);
};
