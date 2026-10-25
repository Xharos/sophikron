import { commandDashboard } from '#lib/server/dashboard';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async (event) => {
	try {
		return Response.json((await commandDashboard(event)) ?? { success: true });
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json(
			{ message: cause.message },
			{ status: cause.status, headers: cause.retryAfter ? { 'Retry-After': cause.retryAfter } : {} }
		);
	}
};
