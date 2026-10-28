import { requireUser } from '#lib/server/forms';
import { api, configuration } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import type { RequestHandler } from './$types';

/** Reveal this member's newly generated link once; never persist it in browser storage. */
export const POST: RequestHandler = async (event) => {
	requireUser(event);
	try {
		const result = await api<{ token: string }>(event, '/timetable/subscription', 'POST');
		return Response.json(
			{ url: `${configuration().origin}/calendar-feed/${result.token}.ics` },
			{ headers: { 'Cache-Control': 'private, no-store' } }
		);
	} catch (cause) {
		if (!(cause instanceof BackendError)) throw cause;
		return Response.json({ message: cause.message }, { status: cause.status });
	}
};
