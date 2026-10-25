import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = ({ locals }) => ({
	user: locals.user,
	establishmentName: process.env.ESTABLISHMENT_NAME?.trim() || 'Sophikron',
	siteOrigin: process.env.ORIGIN || 'http://localhost:3000'
});
