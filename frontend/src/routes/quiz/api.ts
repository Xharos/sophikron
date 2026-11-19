import { resolve } from '$app/paths';

type Command = 'create' | 'edit' | 'archive' | 'delete' | 'preview';

export async function quizAction<T>(
	command: Command,
	subjectId: number,
	questionId: number | undefined,
	data: object
): Promise<T> {
	const response = await fetch(resolve('/quiz/data'), {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ command, subjectId, questionId, data })
	});
	if (!response.ok) {
		const failure: { message?: string } | null = await response.json().catch(() => null);
		throw new Error(
			failure?.message ||
				(response.status === 413
					? 'La fiche et son image dépassent la limite autorisée par le serveur.'
					: 'La demande a échoué. Réessayez dans un instant.')
		);
	}
	return response.json() as Promise<T>;
}
