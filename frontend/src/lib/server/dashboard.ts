import { error, type RequestEvent } from '@sveltejs/kit';
import { canAccess, hasPermission, type PageAccess } from '../access';
import { BackendError } from './backend';
import { api, configuration } from './api';
import type { AccessInvitation } from '../types';

/** JSON endpoints preserve 401 so an expired workspace can return to login. */
function requireAccess(event: RequestEvent, access: PageAccess): void {
	if (!event.locals.user) throw new BackendError(401, 'Votre session a expiré.');
	if (!canAccess(event.locals.user, access))
		throw new BackendError(403, 'Vous n’avez pas accès à cette action.');
}

/** Route identifiers never come from an arbitrary browser-supplied backend URL. */
function identifier(value: unknown): number {
	const id = typeof value === 'number' ? value : Number(value);
	if (!Number.isSafeInteger(id) || id <= 0) error(422, 'Identifiant invalide.');
	return id;
}

/** Only the three known partition kinds can enter a backend route. */
function partitionKind(value: unknown): string {
	if (value !== 'halves' && value !== 'thirds' && value !== 'kholles')
		error(422, 'Type de répartition invalide.');
	return value;
}

/** Expose a small resource vocabulary while keeping query construction on the server. */
export async function readDashboard(event: RequestEvent): Promise<unknown> {
	requireAccess(event, 'staff');
	const admin = hasPermission(event.locals.user, 'users.read');
	const prefix = admin ? '/admin' : '/teaching';
	const resource = event.url.searchParams.get('resource');
	if (resource === 'versions') {
		requireAccess(event, 'admin');
		return api(event, '/admin/versions');
	}
	const query = new URLSearchParams();
	for (const key of [
		'q',
		'role',
		'status',
		'promotion_id',
		'exclude_promotion_id',
		'offset',
		'limit',
		'is_active',
		'year',
		'cursor',
		'event_type',
		'family',
		'user_id',
		'order'
	]) {
		const value = event.url.searchParams.get(key);
		if (value !== null && value !== '') query.set(key, value);
	}
	let path: string;
	switch (resource) {
		case 'calendarSubscription':
			requireAccess(event, 'admin');
			path = `/timetable/subscriptions/users/${identifier(event.url.searchParams.get('id'))}`;
			break;
		case 'customPromotionGroups':
			path = `/promotion-groups/${identifier(event.url.searchParams.get('id'))}/custom/groups`;
			break;
		case 'promotionGroups':
			path = `/promotion-groups/${identifier(event.url.searchParams.get('id'))}`;
			break;
		case 'team':
			requireAccess(event, 'admin');
			path = '/admin/team';
			break;
		case 'promotionArchiveImpact':
			requireAccess(event, 'admin');
			path = `/admin/promotions/${identifier(event.url.searchParams.get('id'))}/archive-impact`;
			break;
		case 'subjects':
			requireAccess(event, 'admin');
			path = '/admin/subjects';
			break;
		case 'site':
			requireAccess(event, 'admin');
			path = '/site';
			break;
		case 'courseImpact':
			requireAccess(event, 'admin');
			path = `/admin/users/${identifier(event.url.searchParams.get('id'))}/course-impact`;
			break;
		case 'summary':
		case 'events':
			requireAccess(event, 'admin');
			path = `/admin/${resource}`;
			break;
		case 'promotions':
			path =
				!admin && !hasPermission(event.locals.user, 'teaching.read')
					? '/promotion-groups/promotions'
					: `${prefix}/promotions`;
			break;
		case 'eventTypes':
			requireAccess(event, 'admin');
			path = '/admin/events/types';
			break;
		case 'users':
			path = `${prefix}/users`;
			break;
		case 'search':
			path = `${prefix}/users/search`;
			break;
		case 'user':
			path = `${prefix}/users/${identifier(event.url.searchParams.get('id'))}`;
			break;
		case 'profile':
			path = `${prefix}/users/${identifier(event.url.searchParams.get('id'))}/profile`;
			break;
		case 'communes':
			requireAccess(event, 'admin');
			path = '/admin/communes';
			break;
		case 'userPromotions':
			requireAccess(event, 'admin');
			path = `/admin/users/${identifier(event.url.searchParams.get('id'))}/promotions`;
			break;
		default:
			error(404, 'Ressource inconnue.');
	}
	return api(event, path + (query.size ? `?${query}` : ''));
}

/** Commands are allowlisted, POST-only and re-authorized by FastAPI. */
export async function commandDashboard(event: RequestEvent): Promise<unknown> {
	requireAccess(event, 'staff');
	let raw: unknown;
	try {
		raw = await event.request.json();
	} catch {
		throw new BackendError(422, 'Demande invalide.');
	}
	if (!raw || typeof raw !== 'object' || !('command' in raw)) error(422, 'Demande invalide.');
	const input = raw as Record<string, unknown>;
	if (input.command === 'updateProfile') {
		const prefix = hasPermission(event.locals.user, 'users.manage') ? '/admin' : '/teaching';
		return api(event, `${prefix}/users/${identifier(input.id)}/profile`, 'PATCH', input.data);
	}
	requireAccess(event, 'admin');
	switch (input.command) {
		case 'calendarSubscription':
			return api(
				event,
				`/timetable/subscriptions/users/${identifier(input.id)}`,
				'POST',
				input.data
			);
		case 'calendarSubscriptionsBulk':
			return api(event, '/timetable/subscriptions/bulk', 'POST', input.data);
		case 'previewGroups':
			return api(
				event,
				`/promotion-groups/${identifier(input.id)}/${partitionKind(input.kind)}/preview`,
				'POST',
				input.data
			);
		case 'saveCustomGroup': {
			const groupId = input.groupId === 0 ? 0 : identifier(input.groupId);
			return api(
				event,
				`/promotion-groups/${identifier(input.id)}/custom/${groupId}`,
				'PUT',
				input.data
			);
		}
		case 'deleteCustomGroup':
			return api(
				event,
				`/promotion-groups/${identifier(input.id)}/custom/${identifier(input.groupId)}`,
				'DELETE',
				input.data
			);
		case 'saveGroups':
			return api(
				event,
				`/promotion-groups/${identifier(input.id)}/${partitionKind(input.kind)}`,
				'PUT',
				input.data
			);
		case 'deleteGroups':
			return api(
				event,
				`/promotion-groups/${identifier(input.id)}/${partitionKind(input.kind)}`,
				'DELETE',
				input.data
			);
		case 'saveSettings':
			return api(event, '/admin/site', 'PUT', input.data);
		case 'createSubject':
			return api(event, '/admin/subjects', 'POST', input.data);
		case 'updateSubject':
			return api(event, `/admin/subjects/${identifier(input.id)}`, 'PUT', input.data);
		case 'archiveSubject':
			return api(event, `/admin/subjects/${identifier(input.id)}`, 'DELETE', input.data);
		case 'createUser':
			return api(event, '/admin/users', 'POST', input.data);
		case 'createPromotion':
			return api(event, '/admin/promotions', 'POST', input.data);
		case 'updatePromotion':
			return api(event, `/admin/promotions/${identifier(input.id)}`, 'PATCH', input.data);
		case 'archiveAccount':
			return api(event, `/admin/users/${identifier(input.id)}/archive`, 'PATCH', input.data);
		case 'addMembers':
			return api(event, `/admin/promotions/${identifier(input.id)}/users`, 'POST', input.data);
		case 'membership':
			if (typeof input.add !== 'boolean') error(422, 'Opération invalide.');
			return api(
				event,
				`/admin/users/${identifier(input.userId)}/promotions/${identifier(input.promotionId)}`,
				input.add ? 'PUT' : 'DELETE'
			);
		case 'invitation': {
			const invitation = await api<AccessInvitation>(
				event,
				`/admin/users/${identifier(input.id)}/access-invitation`,
				'POST'
			);
			return {
				...invitation,
				link: invitation.token
					? `${configuration().origin}/activate#token=${encodeURIComponent(invitation.token)}`
					: undefined
			};
		}
		default:
			error(422, 'Opération inconnue.');
	}
}
