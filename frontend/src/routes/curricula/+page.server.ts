import { error } from '@sveltejs/kit';
import { hasPermission } from '#lib/access';
import { requireUser } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { CurriculumCatalog } from '#lib/curricula';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requireUser(event);
	if (!hasPermission(event.locals.user, 'curricula.read'))
		error(403, 'Accès réservé à l’équipe pédagogique.');
	try {
		return { catalog: await api<CurriculumCatalog>(event, '/curricula/catalog') };
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
