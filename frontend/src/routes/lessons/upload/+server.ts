import type { RequestHandler } from './$types';
import { transferLessonFile } from '#lib/server/lessonFiles';
import { BackendError } from '#lib/server/backend';

export const POST: RequestHandler = async (event) => {
	try {
		return await transferLessonFile(event, true);
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
