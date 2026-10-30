/** Relay private roster PDFs through a fixed, authenticated backend endpoint. */
import type { RequestEvent } from '@sveltejs/kit';
import { hasPermission } from '../access.ts';
import { privatePdf } from './privatePdf.ts';
import { BackendError } from './backend.ts';

export async function promotionAttendance(
	event: RequestEvent,
	transport: typeof fetch = fetch
): Promise<Response> {
	if (!event.locals.user) throw new BackendError(401, 'Votre session a expiré.');
	if (
		!['users.read', 'teaching.read'].some((permission) =>
			hasPermission(event.locals.user, permission)
		)
	)
		throw new BackendError(403, 'Vous n’avez pas accès à cette action.');
	const value = event.url.searchParams.get('promotionId');
	const promotionId = Number(value);
	if (!value || !/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(promotionId))
		throw new BackendError(422, 'Promotion invalide.');
	const variant = event.url.searchParams.get('variant') ?? 'roster';
	if (!['roster', 'halves', 'thirds', 'kholles', 'custom', 'global'].includes(variant))
		throw new BackendError(422, 'Document invalide.');
	const query = variant === 'roster' ? '' : `?variant=${variant}`;
	return privatePdf(
		event,
		`/promotion-groups/${promotionId}/attendance${query}`,
		`presence-promotion-${promotionId}.pdf`,
		transport
	);
}
