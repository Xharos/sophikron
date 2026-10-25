import { fail, redirect } from '@sveltejs/kit';
import { api } from '#lib/server/api';
import { confirmPassword, formFailure, textField } from '#lib/server/forms';
import type { Actions, PageServerLoad } from './$types';
import type { User } from '#lib/types';

export const load: PageServerLoad = ({ locals }) => {
	if (!locals.user) redirect(303, '/login');
	if (!locals.user.is_bootstrap) redirect(303, '/');
};

export const actions: Actions = {
	default: async (event) => {
		if (!event.locals.user?.is_bootstrap)
			return fail(403, { message: 'Installation non autorisée.' });
		const data = await event.request.formData();
		if (!confirmPassword(data))
			return fail(422, { message: 'Les mots de passe ne correspondent pas.' });
		try {
			const user = await api<User>(event, '/auth/setup', 'POST', {
				first_name: textField(data, 'first_name'),
				last_name: textField(data, 'last_name'),
				email: textField(data, 'email'),
				password: textField(data, 'password')
			});
			return { success: true, username: user.username };
		} catch (cause) {
			return formFailure(event, cause);
		}
	}
};
