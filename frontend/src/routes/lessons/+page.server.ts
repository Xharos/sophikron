import { error } from '@sveltejs/kit';
import { requireUser } from '#lib/server/forms';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { LessonPage } from '#lib/lessons';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requireUser(event);
	const raw = Number(event.url.searchParams.get('offset') || '0');
	const offset = Number.isSafeInteger(raw) && raw >= 0 ? raw : 0;
	try {
		return {
			catalogue: await api<LessonPage>(
				event,
				`/lessons?${new URLSearchParams({ offset: String(offset) })}`
			)
		};
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
