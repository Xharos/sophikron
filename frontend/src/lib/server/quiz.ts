import { error, type RequestEvent } from '@sveltejs/kit';
import { canAccessQuiz } from '#lib/quiz';
import { api } from './api';
import { BackendError } from './backend';
import { requireUser } from './forms';

export function quizId(value: unknown): number {
	const number = typeof value === 'string' && /^[1-9]\d*$/.test(value) ? Number(value) : value;
	if (typeof number !== 'number' || !Number.isSafeInteger(number) || number <= 0)
		error(404, 'Identifiant de fiche ou de matière invalide.');
	return number;
}

export function requireQuiz(event: RequestEvent): void {
	requireUser(event);
	if (!canAccessQuiz(event.locals.user))
		error(403, 'Accès réservé aux enseignants et administrateurs.');
}

export async function loadQuiz<T>(event: RequestEvent, path: string): Promise<T> {
	try {
		return await api<T>(event, path);
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
}
