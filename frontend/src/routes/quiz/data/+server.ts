import { error, json } from '@sveltejs/kit';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { quizId, requireQuiz } from '#lib/server/quiz';
import type { RequestHandler } from './$types';

export const POST: RequestHandler = async (event) => {
	requireQuiz(event);
	try {
		const input: unknown = await event.request.json().catch((cause: unknown) => {
			if (cause instanceof BackendError) throw cause;
			error(422, 'Demande invalide.');
		});
		if (!input || typeof input !== 'object' || Array.isArray(input))
			error(422, 'Demande invalide.');
		const { command, subjectId, questionId, data } = input as Record<string, unknown>;
		const collection = `/quiz/subjects/${quizId(subjectId)}/questions`;
		if (command === 'create') return json(await api(event, collection, 'POST', data));
		const path = `${collection}/${quizId(questionId)}`;
		switch (command) {
			case 'edit':
				return json(await api(event, path, 'PUT', data));
			case 'archive':
				await api(event, path, 'PATCH', data);
				return json({});
			case 'delete':
				await api(event, path, 'DELETE', data);
				return json({});
			case 'preview':
				return json(await api(event, `${path}/preview`, 'POST', data));
			default:
				error(404, 'Action inconnue.');
		}
	} catch (cause) {
		if (cause instanceof BackendError)
			return json({ message: cause.message }, { status: cause.status });
		throw cause;
	}
};
