import { isIP } from 'node:net';
import type { Cookies } from '@sveltejs/kit';

export interface BackendConfig {
	origin: string;
	backendOrigin: string;
	secure: boolean;
}

export interface BackendEvent {
	request: Request;
	cookies: Cookies;
	getClientAddress(): string;
}

export type BackendMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

/** An API failure safe to display; credentials and raw response bodies are never retained. */
export class BackendError extends Error {
	status: number;
	retryAfter: string | null;

	constructor(status: number, message: string, retryAfter: string | null = null) {
		super(message);
		this.status = status;
		this.retryAfter = retryAfter;
	}
}

export function sessionCookie(config: BackendConfig): string {
	return config.secure ? '__Host-sophikron_session' : 'sophikron_session_dev';
}

/** Validate before adding trusted headers, including for native HTML form submissions. */
export function validateOrigin(request: Request, origin: string): void {
	if (['GET', 'HEAD', 'OPTIONS'].includes(request.method)) return;
	if (request.headers.get('origin') !== origin) {
		throw new BackendError(403, 'Origine de la demande refusée.');
	}
}

/** Copy only the expected host-only session cookie, preserving expiry and deletion. */
export function relayCookies(response: Response, cookies: Cookies, config: BackendConfig): void {
	const name = sessionCookie(config);
	for (const header of response.headers.getSetCookie()) {
		const [pair, ...parts] = header.split(';');
		const separator = pair.indexOf('=');
		if (pair.slice(0, separator).trim() !== name) continue;
		const attributes = new Map(
			parts.map((part) => {
				const [key, ...values] = part.trim().split('=');
				return [key.toLowerCase(), values.join('=')] as const;
			})
		);
		if (
			attributes.has('domain') ||
			attributes.get('path') !== '/' ||
			!attributes.has('httponly') ||
			attributes.get('samesite')?.toLowerCase() !== 'lax' ||
			(config.secure && !attributes.has('secure'))
		) {
			throw new BackendError(502, 'Réponse du service invalide.');
		}
		const maxAge = attributes.has('max-age') ? Number(attributes.get('max-age')) : undefined;
		if (maxAge !== undefined && (!Number.isSafeInteger(maxAge) || maxAge < 0)) {
			throw new BackendError(502, 'Réponse du service invalide.');
		}
		const expires = attributes.has('expires') ? new Date(attributes.get('expires')!) : undefined;
		if (expires && !Number.isFinite(expires.getTime())) {
			throw new BackendError(502, 'Réponse du service invalide.');
		}
		cookies.set(name, pair.slice(separator + 1).trim(), {
			path: '/',
			httpOnly: true,
			secure: config.secure,
			sameSite: 'lax',
			maxAge,
			expires
		});
	}
}

/** One request-scoped bridge: never forward arbitrary browser cookies or proxy headers. */
export async function requestBackend<T>(
	event: BackendEvent,
	config: BackendConfig,
	path: string,
	method: BackendMethod = 'GET',
	body?: unknown,
	transport: typeof fetch = fetch
): Promise<T> {
	validateOrigin(event.request, config.origin);
	if (method !== 'GET' && event.request.method !== 'POST') {
		throw new BackendError(405, 'Cette opération exige une soumission de formulaire.');
	}
	const [pathname] = path.split('?');
	if (
		!/^\/(?:(?:auth|admin|teaching)\/[a-zA-Z0-9/-]+|promotion-groups\/(?:promotions(?:\/[1-9]\d*)?|[1-9]\d*(?:\/(?:halves|thirds|kholles)(?:\/preview)?)?)|lessons(?:\/[a-zA-Z0-9/-]+)?|site)$/.test(
			pathname
		) ||
		path.includes('#')
	) {
		throw new BackendError(500, 'Chemin de service invalide.');
	}
	const address = event.getClientAddress().replace(/^::ffff:/, '');
	if (!isIP(address)) throw new BackendError(503, 'Adresse client indisponible.');
	const headers = new Headers({ accept: 'application/json', 'x-forwarded-for': address });
	const cookie = event.cookies.get(sessionCookie(config));
	if (cookie && /^[A-Za-z0-9_-]{1,128}$/.test(cookie)) {
		headers.set('cookie', `${sessionCookie(config)}=${cookie}`);
	}
	if (method !== 'GET') {
		headers.set('origin', config.origin);
		headers.set('x-csrf-protection', '1');
		if (body !== undefined) headers.set('content-type', 'application/json');
	}
	let response: Response;
	try {
		response = await transport(`${config.backendOrigin}/api/v1${path}`, {
			method,
			headers,
			body: body === undefined ? undefined : JSON.stringify(body),
			redirect: 'error',
			signal: AbortSignal.timeout(15000),
			cache: 'no-store'
		});
	} catch {
		throw new BackendError(503, 'Le service est indisponible. Réessayez plus tard.');
	}
	relayCookies(response, event.cookies, config);
	if (!response.ok) {
		if (response.status === 401) {
			event.cookies.delete(sessionCookie(config), { path: '/', secure: config.secure });
		}
		let message = 'La demande n’a pas pu être acceptée.';
		try {
			const data: unknown = await response.json();
			if (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string') {
				message = data.detail;
			}
		} catch {
			/* Keep the generic message for non-JSON infrastructure failures. */
		}
		const retry = response.headers.get('retry-after');
		throw new BackendError(
			response.status,
			message,
			retry && /^\d{1,8}$/.test(retry) ? retry : null
		);
	}
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}
