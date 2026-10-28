import { requirePageAccess } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError, type BackendMethod } from '#lib/server/backend';
import type { RequestHandler } from './$types';

/** Route only explicitly allowed administrator operations through the same-origin BFF. */
export const POST: RequestHandler = async (event) => {
	requirePageAccess(event, 'admin');
	const body: unknown = await event.request.json();
	if (!body || typeof body !== 'object') return new Response('Demande invalide.', { status: 422 });
	const command = body as { path?: unknown; method?: unknown; data?: unknown };
	if (
		typeof command.path !== 'string' ||
		!/^(?:preferences|school-years(?:\/[1-9]\d{3})?|calendars(?:\/[1-9]\d*(?:\/(?:archive|restore))?)?|rooms(?:\/[1-9]\d*)?|years\/[1-9]\d*\/(?:preview|settings(?:\/preview)?|series(?:\/[a-f0-9]{32})?))$/.test(
			command.path
		) ||
		!['POST', 'PUT', 'DELETE'].includes(String(command.method))
	) {
		return Response.json({ message: 'Action invalide.' }, { status: 422 });
	}
	try {
		return Response.json(
			await api(event, `/timetable/${command.path}`, command.method as BackendMethod, command.data)
		);
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
