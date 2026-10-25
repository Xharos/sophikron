import { error } from '@sveltejs/kit';
import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { hasPermission } from '#lib/access';
import { BackendError } from '#lib/server/backend';
import type { FullProfile } from '#lib/types';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event, 'staff');
	const id = Number(event.url.searchParams.get('id'));
	if (!Number.isSafeInteger(id) || id <= 0) error(422, 'Identifiant de compte invalide.');
	const prefix = hasPermission(event.locals.user, 'users.manage') ? '/admin' : '/teaching';
	try {
		return { profile: await api<FullProfile>(event, `${prefix}/users/${id}/profile`) };
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
