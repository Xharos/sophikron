import { error, json } from '@sveltejs/kit';
import { hasPermission } from '#lib/access';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

function id(value: unknown): number {
	if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0)
		error(422, 'Identifiant invalide.');
	return value;
}

export const POST: RequestHandler = async (event) => {
	if (!event.locals.user) return json({ message: 'Votre session a expiré.' }, { status: 401 });
	if (!hasPermission(event.locals.user, 'curricula.read')) error(403, 'Accès refusé.');
	let raw: unknown;
	try {
		raw = await event.request.json();
	} catch {
		error(422, 'Demande invalide.');
	}
	if (!raw || typeof raw !== 'object') error(422, 'Demande invalide.');
	const input = raw as Record<string, unknown>;
	try {
		if (input.command === 'catalog') return json(await api(event, '/curricula/catalog'));
		if (input.command === 'undo')
			return json(
				await api(event, `/curricula/${id(input.curriculum_id)}/undo`, 'POST', input.data)
			);
		if (input.command === 'graph')
			return json(
				await api(event, `/curricula/${id(input.curriculum_id)}/subjects/${id(input.subject_id)}`)
			);
		if (input.command === 'saveNode' || input.command === 'deleteNode') {
			const path = `/curricula/${id(input.curriculum_id)}/subjects/${id(input.subject_id)}/nodes`;
			if (input.command === 'deleteNode')
				return json(await api(event, `${path}/${id(input.id)}`, 'DELETE', input.data));
			return json(
				await api(
					event,
					input.id ? `${path}/${id(input.id)}` : path,
					input.id ? 'PUT' : 'POST',
					input.data
				)
			);
		}
		if (!hasPermission(event.locals.user, 'curricula.manage'))
			error(403, 'Accès réservé aux administrateurs.');
		if (input.command === 'saveCurriculum') {
			const path = '/curricula';
			return json(
				await api(
					event,
					input.id ? `${path}/${id(input.id)}` : path,
					input.id ? 'PUT' : 'POST',
					input.data
				)
			);
		}
		error(404, 'Action inconnue.');
	} catch (cause) {
		if (cause instanceof BackendError)
			return json({ message: cause.message }, { status: cause.status });
		throw cause;
	}
};
