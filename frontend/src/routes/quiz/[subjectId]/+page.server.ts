import { error } from '@sveltejs/kit';
import type { QuizEdit, QuizPreview, QuizSubject } from '#lib/quiz';
import { loadQuiz, quizId, requireQuiz } from '#lib/server/quiz';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requireQuiz(event);
	const subjectId = quizId(event.params.subjectId);
	const path = `/quiz/subjects/${subjectId}`;
	const subject = await loadQuiz<QuizSubject>(event, path);
	const preview = event.url.searchParams.get('fiche');
	const edit = event.url.searchParams.get('modifier');
	if (edit !== null) {
		if (!subject.can_edit) error(403, 'Vous ne pouvez pas modifier les fiches de cette matière.');
		const question =
			edit === 'nouvelle'
				? null
				: await loadQuiz<QuizEdit>(event, `${path}/questions/${quizId(edit)}?edit=true`);
		return { subject, view: 'edit' as const, question };
	}
	if (preview !== null) {
		const question = await loadQuiz<QuizPreview>(event, `${path}/questions/${quizId(preview)}`);
		return { subject, view: 'preview' as const, question };
	}
	return { subject, view: 'list' as const, question: null };
};
