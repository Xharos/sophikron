import { readLessonOptions } from '#lib/server/lessons';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	try {
		return Response.json(await readLessonOptions(event));
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
