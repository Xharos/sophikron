import { changePassword, requirePageAccess } from '#lib/server/forms';
import type { Actions, PageServerLoad } from './$types';
import { api, configuration } from '#lib/server/api';
import type { FullProfile, Promotion } from '#lib/types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event);
	const account = event.locals.user!;
	const subscription = account.is_bootstrap
		? null
		: await api<{ token: string | null; revoked: boolean }>(event, '/timetable/subscription');
	return {
		account,
		calendarSubscription: subscription?.token
			? {
					revoked: subscription.revoked,
					url: subscription.token
						? `${configuration().origin}/calendar-feed/${subscription.token}.ics`
						: null
				}
			: null,
		profile: account.is_bootstrap ? null : await api<FullProfile>(event, '/auth/me/profile'),
		promotions: account.is_bootstrap ? [] : await api<Promotion[]>(event, '/auth/me/promotions')
	};
};

export const actions: Actions = { default: changePassword };
