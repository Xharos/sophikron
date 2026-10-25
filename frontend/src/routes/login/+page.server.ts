import { redirect } from '@sveltejs/kit';
import { api } from '#lib/server/api';
import { formFailure, textField } from '#lib/server/forms';
import type { User } from '#lib/types';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ locals }) => {
	if (locals.user) redirect(303, '/');
};

export const actions: Actions = {
	default: async (event) => {
		const data = await event.request.formData();
		try {
			await api<User>(event, '/auth/login', 'POST', {
				identifier: textField(data, 'identifier'),
				password: textField(data, 'password')
			});
		} catch (cause) {
			return formFailure(event, cause);
		}
		redirect(303, '/');
	}
};
