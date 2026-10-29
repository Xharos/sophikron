import { resolve } from '$app/paths';

export interface TimetableCommandResult {
	id?: number;
	revision?: string;
	number?: number;
	skipped?: number;
}

/** Route browser mutations through the existing origin-protected BFF. */
export async function timetableCommand<T = TimetableCommandResult>(
	path: string,
	method: 'POST' | 'PUT' | 'DELETE',
	data: unknown
): Promise<T> {
	const response = await fetch(resolve('/timetable/command'), {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ path, method, data })
	});
	if (!response.headers.get('content-type')?.includes('application/json')) {
		const message = await response.text();
		throw new Error(
			response.ok ? 'Réponse du serveur invalide.' : message || 'Enregistrement impossible.'
		);
	}
	const result = (await response.json()) as T & { message?: string };
	if (!response.ok) throw new Error(result.message ?? 'Enregistrement impossible.');
	return result;
}
