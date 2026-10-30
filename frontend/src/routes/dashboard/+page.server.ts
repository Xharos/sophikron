import { requirePageAccess } from '#lib/server/forms';
import { error, redirect } from '@sveltejs/kit';
import { hasPermission } from '#lib/access';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { Promotion } from '#lib/types';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	if (event.locals.user?.is_bootstrap) redirect(303, '/setup');
	requirePageAccess(event, 'staff');
	let initialPromotion: Promotion | null = null;
	const promotion = event.url.searchParams.get('promotion');
	if (promotion !== null) {
		const id = Number(promotion);
		if (!Number.isSafeInteger(id) || id <= 0) error(422, 'Identifiant de promotion invalide.');
		try {
			initialPromotion = await api<Promotion>(event, `/promotion-groups/promotions/${id}`);
		} catch (cause) {
			if (cause instanceof BackendError) error(cause.status, cause.message);
			throw cause;
		}
	}
	return {
		initialPromotion,
		editPromotion:
			hasPermission(event.locals.user, 'promotions.manage') &&
			initialPromotion !== null &&
			event.url.searchParams.get('edit') === '1',
		administrator: hasPermission(event.locals.user, 'users.manage'),
		section: event.url.searchParams.get('tab') ?? '',
		create: event.url.searchParams.get('create') === 'account'
	};
};
