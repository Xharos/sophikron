import { error } from '@sveltejs/kit';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { requireUser } from '#lib/server/forms';
import { lessonIdentifier } from '#lib/server/lessons';
import type { LessonDetail } from '#lib/lessons';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requireUser(event);
	try {
		return {
			lesson: await api<LessonDetail>(event, `/lessons/${lessonIdentifier(event.params.id)}`)
		};
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
