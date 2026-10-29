import type { RequestHandler } from './$types';
import { promotionAttendance } from '#lib/server/promotionAttendance';
import { BackendError } from '#lib/server/backend';

export const GET: RequestHandler = async (event) => {
	try {
		return await promotionAttendance(event);
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return new Response(cause.message, {
			status: cause.status,
			headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'private, no-store' }
		});
	}
};
