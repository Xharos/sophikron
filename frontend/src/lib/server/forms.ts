import { error, fail, redirect, type RequestEvent } from '@sveltejs/kit';
import { BackendError } from './backend';
import { canAccess, type PageAccess } from '../access';
import { api } from './api';
import { loginDestination } from '../loginRedirect';

/** Protect page loads as well as direct URL visits, using the profile verified by FastAPI. */
export function requirePageAccess(event: RequestEvent, access: PageAccess = 'authenticated'): void {
	if (!event.locals.user) redirect(303, loginDestination(event.url.pathname + event.url.search));
	if (!canAccess(event.locals.user, access)) error(403, 'Vous n’avez pas accès à cette page.');
}

export function requireUser(event: RequestEvent, admin = false): void {
	if (!event.locals.user) redirect(303, loginDestination(event.url.pathname + event.url.search));
	if (event.locals.user.is_bootstrap) redirect(303, '/setup');
	if (admin && !canAccess(event.locals.user, 'admin'))
		error(403, 'Accès réservé aux administrateurs.');
}

/** Never return form input containing a password or an activation token on failure. */
export function formFailure(event: RequestEvent, cause: unknown) {
	if (!(cause instanceof BackendError)) throw cause;
	if (cause.retryAfter) event.setHeaders({ 'Retry-After': cause.retryAfter });
	return fail(cause.status, { message: cause.message });
}

export function textField(data: FormData, name: string): string {
	const value = data.get(name);
	return typeof value === 'string' ? value : '';
}

export function confirmPassword(data: FormData): boolean {
	return textField(data, 'password') === textField(data, 'confirmation');
}

/** Share the password form action between account settings and the existing standalone route. */
export async function changePassword(event: RequestEvent) {
	requireUser(event);
	const data = await event.request.formData();
	if (!confirmPassword(data))
		return fail(422, { message: 'Les mots de passe ne correspondent pas.' });
	try {
		await api(event, '/auth/change-password', 'POST', {
			current_password: textField(data, 'current_password'),
			new_password: textField(data, 'password')
		});
	} catch (cause) {
		return formFailure(event, cause);
	}
	redirect(303, '/login?notice=password');
}
