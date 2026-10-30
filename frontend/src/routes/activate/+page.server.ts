import { fail, redirect } from '@sveltejs/kit';
import { api } from '#lib/server/api';
import { confirmPassword, formFailure, textField } from '#lib/server/forms';
import type { Actions } from './$types';

export const actions: Actions = {
	default: async (event) => {
		const data = await event.request.formData();
		if (!confirmPassword(data))
			return fail(422, { message: 'Les mots de passe ne correspondent pas.' });
		try {
			await api(event, '/auth/activate', 'POST', {
				token: textField(data, 'token'),
				password: textField(data, 'password')
			});
		} catch (cause) {
			return formFailure(event, cause);
		}
		redirect(303, '/login?notice=activated');
	}
};
