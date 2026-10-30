/** Validate view identifiers before relaying a private, server-generated timetable PDF. */
import type { RequestEvent } from '@sveltejs/kit';
import { hasPermission } from '../access.ts';
import { BackendError } from './backend.ts';
import { privatePdf } from './privatePdf.ts';

export async function timetablePdf(
	event: RequestEvent,
	transport: typeof fetch = fetch
): Promise<Response> {
	if (!event.locals.user) throw new BackendError(401, 'Votre session a expiré.');
	if (
		!['users.manage', 'teaching.read', 'kholleur.access'].some((permission) =>
			hasPermission(event.locals.user, permission)
		)
	)
		throw new BackendError(403, 'Vous n’avez pas accès aux emplois du temps.');
	const identifier = event.params.id ?? '';
	const year = event.url.searchParams.get('year_id') ?? '';
	const day = event.url.searchParams.get('day') ?? '';
	const node = event.url.searchParams.get('node') ?? 'promotion';
	if (
		![identifier, year].every(
			(value) => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))
		) ||
		!/^\d{4}-\d{2}-\d{2}$/.test(day) ||
		!Number.isFinite(Date.parse(day)) ||
		new Date(day).toISOString().slice(0, 10) !== day ||
		!/^(promotion|unassigned|(halves|thirds|kholles|custom|student)-[1-9][0-9]{0,15})$/.test(node)
	)
		throw new BackendError(422, 'Vue d’emploi du temps invalide.');
	const query = new URLSearchParams({ year_id: year, day, node });
	return privatePdf(
		event,
		`/timetable/calendars/${identifier}/pdf?${query}`,
		`emploi-du-temps-${identifier}.pdf`,
		transport
	);
}
