import { redirect } from '@sveltejs/kit';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { formFailure } from '#lib/server/forms';
import type { Actions } from './$types';

export const actions: Actions = {
	default: async (event) => {
		try {
			if (event.locals.user) await api(event, '/auth/logout', 'POST');
		} catch (cause) {
			if (!(cause instanceof BackendError && cause.status === 401))
				return formFailure(event, cause);
		}
		redirect(303, '/');
	}
};
