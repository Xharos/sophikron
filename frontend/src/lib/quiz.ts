import type { Subject } from '#lib/site';
import type { User } from '#lib/types';

type SubjectIdentity = Pick<Subject, 'id' | 'name' | 'icon' | 'color'>;

export interface QuizStats extends SubjectIdentity {
	is_active: boolean;
	total: number;
	archived: number;
}

export interface QuizSummary {
	id: number;
	title: string;
	archived: boolean;
	version: number;
}

export interface QuizSubject extends SubjectIdentity {
	can_edit: boolean;
	questions: QuizSummary[];
	competencies: { id: number; name: string; curriculum: string }[];
}

export type QuizRule =
	| { kind: 'choice'; options: string[]; correct: number[] }
	| { kind: 'number'; expected: string; tolerance: string }
	| { kind: 'text'; accepted: string[] };

export interface QuizPreview extends QuizSummary {
	statement: string;
	prompt: string;
	kind: QuizRule['kind'];
	options: string[];
	image: string | null;
	image_alt: string;
}

export interface QuizEdit extends QuizPreview {
	rule: QuizRule;
	competency_ids: number[];
}

export function canAccessQuiz(user: User | null): boolean {
	return (
		!!user &&
		!user.is_bootstrap &&
		user.roles.some((role) => role === 'teacher' || role === 'admin')
	);
}
