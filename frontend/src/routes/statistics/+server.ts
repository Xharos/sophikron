import type { RequestHandler } from './$types';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { requireLessonSession, lessonIdentifier } from '#lib/server/lessons';
import { hasPermission } from '#lib/access';

export const GET: RequestHandler = async (event) => {
	try {
		requireLessonSession(event);
		const period = event.url.searchParams.get('period') || 'week';
		if (!['day', 'week', 'month'].includes(period))
			throw new BackendError(422, 'Période invalide.');
		const id = event.url.searchParams.get('lessonId');
		const path =
			id !== null
				? `/lessons/${lessonIdentifier(id)}/statistics`
				: hasPermission(event.locals.user, 'statistics.read')
					? '/admin/statistics'
					: '/teaching/statistics';
		return Response.json(await api(event, `${path}?period=${period}`), {
			headers: { 'Cache-Control': 'private, no-store' }
		});
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json(
			{ message: cause.message },
			{ status: cause.status, headers: { 'Cache-Control': 'private, no-store' } }
		);
	}
};
