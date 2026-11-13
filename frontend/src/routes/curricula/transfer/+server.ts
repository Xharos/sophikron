import { error, json } from '@sveltejs/kit';
import { hasPermission } from '#lib/access';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async (event) => {
	if (!hasPermission(event.locals.user, 'curricula.read')) error(403, 'Accès refusé.');
	let raw: unknown;
	try {
		raw = await event.request.json();
	} catch {
		error(422, 'JSON invalide.');
	}
	if (!raw || typeof raw !== 'object') error(422, 'Demande invalide.');
	const input = raw as Record<string, unknown>;
	if (
		typeof input.command !== 'string' ||
		!['import', 'export'].includes(input.command) ||
		typeof input.curriculum_id !== 'number' ||
		!Number.isSafeInteger(input.curriculum_id) ||
		input.curriculum_id <= 0 ||
		typeof input.subject_id !== 'number' ||
		!Number.isSafeInteger(input.subject_id) ||
		input.subject_id <= 0
	)
		error(422, 'Demande invalide.');
	const path = `/curricula/${input.curriculum_id}/subjects/${input.subject_id}/${input.command}`;
	try {
		return json(
			await api(
				event,
				path,
				input.command === 'export' ? 'GET' : 'POST',
				input.command === 'export'
					? undefined
					: { expected_version: input.expected_version, document: input.document }
			)
		);
	} catch (cause) {
		if (cause instanceof BackendError)
			return json({ message: cause.message }, { status: cause.status });
		throw cause;
	}
};
