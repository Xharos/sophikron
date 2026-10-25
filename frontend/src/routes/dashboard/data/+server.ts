import { readDashboard } from '#lib/server/dashboard';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async (event) => {
	try {
		return Response.json(await readDashboard(event));
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json(
			{ message: cause.message },
			{ status: cause.status, headers: cause.retryAfter ? { 'Retry-After': cause.retryAfter } : {} }
		);
	}
};
