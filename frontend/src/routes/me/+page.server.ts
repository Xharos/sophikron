import { redirect } from '@sveltejs/kit';
import { changePassword } from '#lib/server/forms';
import type { Actions, PageServerLoad } from './$types';
import { api } from '#lib/server/api';
import type { FullProfile, Promotion } from '#lib/types';

export const load: PageServerLoad = async (event) => {
	if (!event.locals.user) redirect(303, '/login');
	return {
		account: event.locals.user,
		profile: event.locals.user.is_bootstrap
			? null
			: await api<FullProfile>(event, '/auth/me/profile'),
		promotions: event.locals.user.is_bootstrap
			? []
			: await api<Promotion[]>(event, '/auth/me/promotions')
	};
};

export const actions: Actions = { default: changePassword };
