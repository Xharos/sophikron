import type { LayoutServerLoad } from './$types';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { PublicSite } from '#lib/site';
import { themeCookie, themePreference } from '#lib/theme';

export const load: LayoutServerLoad = async (event) => {
	let site: PublicSite | null = null;
	try {
		site = await api<PublicSite>(event, '/site');
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
	}
	event.setHeaders({ 'cache-control': 'no-store' });
	return {
		themePreference: themePreference(event.cookies.get(themeCookie)),
		user: event.locals.user,
		site,
		establishmentName: site?.settings.name ?? 'Sophikron',
		siteOrigin: process.env.ORIGIN || 'http://localhost:3000'
	};
};
