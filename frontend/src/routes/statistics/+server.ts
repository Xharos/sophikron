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
		if (event.url.searchParams.get('resource') === 'monitoring') {
			if (!hasPermission(event.locals.user, 'statistics.read'))
				throw new BackendError(403, 'Monitoring réservé aux administrateurs.');
			const query = new URLSearchParams({ period });
			for (const key of ['category', 'interval']) {
				const value = event.url.searchParams.get(key);
				if (value) query.set(key, value);
			}
			return Response.json(await api(event, `/admin/monitoring?${query}`), {
				headers: { 'Cache-Control': 'private, no-store' }
			});
		}
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
