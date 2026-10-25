import type { RequestEvent } from '@sveltejs/kit';
import { requestBackend, type BackendConfig, type BackendMethod } from './backend';

/** Only server code reads these variables. No PUBLIC_ variable contains a credential. */
export function configuration(): BackendConfig {
	const origin = process.env.ORIGIN || 'http://localhost:3000';
	const backendOrigin = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000';
	for (const value of [origin, backendOrigin]) {
		const url = new URL(value);
		if (!['http:', 'https:'].includes(url.protocol) || url.origin !== value) {
			throw new Error('Invalid server origin configuration');
		}
	}
	if (process.env.NODE_ENV === 'production' && !process.env.ORIGIN) {
		throw new Error('ORIGIN is required in production');
	}
	return { origin, backendOrigin, secure: new URL(origin).protocol === 'https:' };
}

export function api<T>(
	event: RequestEvent,
	path: string,
	method: BackendMethod = 'GET',
	body?: unknown
): Promise<T> {
	return requestBackend<T>(event, configuration(), path, method, body);
}
