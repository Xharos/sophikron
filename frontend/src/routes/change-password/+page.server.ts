import { changePassword, requireUser } from '#lib/server/forms';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = (event) => {
	requireUser(event);
};
export const actions: Actions = { default: changePassword };
