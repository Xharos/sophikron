import type { DirectoryUser, Page, Promotion } from './types';
import type { Subject } from './site';
import { loginDestination } from './loginRedirect.ts';
export { roleLabels } from './roles.ts';

/** Same-origin dashboard transport; credentials and keys remain in server code. */
async function responseData<T>(response: Response): Promise<T> {
	if (response.status === 401) {
		window.location.assign(
			loginDestination(window.location.pathname + window.location.search + window.location.hash)
		);
		throw new Error('Votre session a expiré.');
	}
	let body: unknown;
	try {
		body = await response.json();
	} catch {
		throw new Error('Le serveur est momentanément indisponible. Réessayez.');
	}
	if (!response.ok) {
		const failure = body as { message?: unknown; detail?: unknown };
		const message = failure?.message ?? failure?.detail;
		throw new Error(typeof message === 'string' ? message : 'La demande a échoué.');
	}
	return body as T;
}

export async function read<T>(
	resource: string,
	params: Record<string, string | number | boolean | undefined> = {},
	signal?: AbortSignal
): Promise<T> {
	const query = new URLSearchParams({ resource });
	for (const [key, value] of Object.entries(params))
		if (value !== undefined && value !== '') query.set(key, String(value));
	return responseData<T>(await fetch(`/dashboard/data?${query}`, { signal, cache: 'no-store' }));
}

export async function command<T>(name: string, payload: Record<string, unknown> = {}): Promise<T> {
	return responseData<T>(
		await fetch('/dashboard/command', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ command: name, ...payload })
		})
	);
}

/** Use backend category filtering so combined teaching roles share one result limit and ranking. */
export async function promotionCandidates(
	category: 'user' | 'teaching',
	query: string,
	signal?: AbortSignal,
	excludePromotionId?: number
): Promise<DirectoryUser[]> {
	const q = query.trim();
	if (q.length === 1) return [];
	if (q.length >= 2)
		return read<DirectoryUser[]>(
			'search',
			{ q, role: category, limit: 20, exclude_promotion_id: excludePromotionId },
			signal
		);
	return (
		await read<Page<DirectoryUser>>(
			'users',
			{ role: category, limit: 20, exclude_promotion_id: excludePromotionId },
			signal
		)
	).items;
}

export async function activePromotions(): Promise<Promotion[]> {
	const items: Promotion[] = [];
	let offset = 0;
	let total = 1;
	while (offset < total) {
		const page = await read<Page<Promotion>>('promotions', { is_active: true, offset, limit: 100 });
		items.push(...page.items);
		total = page.total;
		offset += 100;
		if (page.items.length === 0) break;
	}
	return items;
}

/** Load every available subject for administrator assignment forms. */
export async function activeSubjects(): Promise<Subject[]> {
	const items: Subject[] = [];
	let offset = 0,
		total = 1;
	while (offset < total) {
		const page = await read<Page<Subject>>('subjects', { is_active: true, offset, limit: 100 });
		items.push(...page.items);
		total = page.total;
		offset += 100;
		if (!page.items.length) break;
	}
	return items;
}

export function formatDate(value: string | null | undefined): string {
	return value
		? new Intl.DateTimeFormat('fr-FR', {
				dateStyle: 'medium',
				timeStyle: 'short',
				timeZone: 'Europe/Paris'
			}).format(new Date(value))
		: '—';
}

export const statusLabels: Record<string, string> = {
	active: 'Actif',
	pending_activation: 'À activer',
	disabled: 'Archivé'
};
