import { loadQuiz, requireQuiz } from '#lib/server/quiz';
import type { QuizStats } from '#lib/quiz';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requireQuiz(event);
	return { subjects: await loadQuiz<QuizStats[]>(event, '/quiz') };
};
