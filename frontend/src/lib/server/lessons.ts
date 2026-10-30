/** Bounded course BFF: no browser-controlled arbitrary API URL or HTTP method. */
import type { RequestEvent } from '@sveltejs/kit';
import { api } from './api.ts';
import { BackendError } from './backend.ts';
import { canAccess } from '../access.ts';

export function lessonIdentifier(value: unknown): number {
	const identifier = typeof value === 'number' ? value : Number(value);
	if (!Number.isSafeInteger(identifier) || identifier <= 0)
		throw new BackendError(422, 'Identifiant invalide.');
	return identifier;
}

export function requireLessonSession(event: RequestEvent): void {
	if (!event.locals.user) throw new BackendError(401, 'Votre session a expiré.');
	if (event.locals.user.is_bootstrap)
		throw new BackendError(403, 'Accès réservé aux comptes permanents.');
}

export async function commandLesson(event: RequestEvent): Promise<unknown> {
	requireLessonSession(event);
	if (!canAccess(event.locals.user, 'staff'))
		throw new BackendError(403, 'Accès réservé aux enseignants.');
	let raw: unknown;
	try {
		raw = await event.request.json();
	} catch {
		throw new BackendError(422, 'Demande invalide.');
	}
	if (!raw || typeof raw !== 'object' || Array.isArray(raw))
		throw new BackendError(422, 'Demande invalide.');
	const input = raw as Record<string, unknown>;
	if (input.command === 'create') return api(event, '/lessons', 'POST', input.data);
	const path = `/lessons/${lessonIdentifier(input.lessonId)}`;
	switch (input.command) {
		case 'reserveUpload':
			return api(event, `${path}/uploads`, 'POST', input.data);
		case 'cancelUpload': {
			if (typeof input.uploadId !== 'string' || !/^[0-9a-f]{32}$/.test(input.uploadId))
				throw new BackendError(422, 'Identifiant de dépôt invalide.');
			await api(event, `${path}/uploads/${input.uploadId}`, 'DELETE');
			return { success: true };
		}
		case 'removeLesson':
			await api(event, path, 'DELETE', input.data);
			return { success: true };
		case 'changeTable':
			return api(
				event,
				`${path}/elements/${lessonIdentifier(input.elementId)}/table`,
				'POST',
				input.data
			);
		case 'transfer':
			return api(event, `${path}/responsibility`, 'PUT', input.data);
		case 'update':
			return api(event, path, 'PUT', input.data);
		case 'addElement':
			return api(event, `${path}/elements`, 'POST', input.data);
		case 'updateElement':
			return api(event, `${path}/elements/${lessonIdentifier(input.elementId)}`, 'PUT', input.data);
		case 'removeElement':
			return api(
				event,
				`${path}/elements/${lessonIdentifier(input.elementId)}`,
				'DELETE',
				input.data
			);
		case 'moveElement':
			return api(
				event,
				`${path}/elements/${lessonIdentifier(input.elementId)}/move`,
				'POST',
				input.data
			);
		case 'addCollaborator':
			return api(
				event,
				`${path}/collaborators/${lessonIdentifier(input.userId)}`,
				'PUT',
				input.data
			);
		case 'removeCollaborator':
			return api(
				event,
				`${path}/collaborators/${lessonIdentifier(input.userId)}`,
				'DELETE',
				input.data
			);
		case 'grantPromotion':
			return api(
				event,
				`${path}/promotions/${lessonIdentifier(input.promotionId)}`,
				'PUT',
				input.data
			);
		case 'revokePromotion':
			return api(
				event,
				`${path}/promotions/${lessonIdentifier(input.promotionId)}`,
				'DELETE',
				input.data
			);
		default:
			throw new BackendError(404, 'Action inconnue.');
	}
}

export async function readLessonOptions(event: RequestEvent): Promise<unknown> {
	requireLessonSession(event);
	if (event.url.searchParams.get('resource') === 'documentLimits')
		return api(event, '/lessons/document-limits');
	if (event.url.searchParams.get('resource') === 'subjects') {
		const offset = event.url.searchParams.get('offset') || '0';
		return api(event, `/lessons/subject-options?offset=${encodeURIComponent(offset)}`);
	}
	const path = `/lessons/${lessonIdentifier(event.url.searchParams.get('lessonId'))}`;
	const query = new URLSearchParams();
	switch (event.url.searchParams.get('resource')) {
		case 'responsible':
			query.set('q', event.url.searchParams.get('q') || '');
			query.set('subject_id', String(lessonIdentifier(event.url.searchParams.get('subjectId'))));
			return api(event, `${path}/responsible-options?${query}`);
		case 'promotions':
			query.set('offset', event.url.searchParams.get('offset') || '0');
			query.set('limit', '50');
			return api(event, `${path}/promotion-options?${query}`);
		case 'teachers':
			query.set('q', event.url.searchParams.get('q') || '');
			return api(event, `${path}/teacher-options?${query}`);
		default:
			throw new BackendError(404, 'Ressource inconnue.');
	}
}
