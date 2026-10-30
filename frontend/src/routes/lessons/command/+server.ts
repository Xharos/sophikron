import { commandLesson } from '#lib/server/lessons';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async (event) => {
	try {
		return Response.json(await commandLesson(event));
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
