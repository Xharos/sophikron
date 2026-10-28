import { changePassword, requirePageAccess } from '#lib/server/forms';
import type { Actions, PageServerLoad } from './$types';
import { api } from '#lib/server/api';
import type { FullProfile, Promotion } from '#lib/types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event);
	const account = event.locals.user!;
	return {
		account,
		calendarSubscription:
			account.is_bootstrap ||
			!account.roles.some((role) => ['user', 'teacher', 'kholleur'].includes(role))
				? null
				: await api<{ exists: boolean }>(event, '/timetable/subscription'),
		profile: account.is_bootstrap ? null : await api<FullProfile>(event, '/auth/me/profile'),
		promotions: account.is_bootstrap ? [] : await api<Promotion[]>(event, '/auth/me/promotions')
	};
};

export const actions: Actions = { default: changePassword };
