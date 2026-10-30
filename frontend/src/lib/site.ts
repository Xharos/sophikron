import type { LessonIcon } from './lessons';

export interface Subject {
	id: number;
	name: string;
	icon: LessonIcon;
	color: string;
	is_active: boolean;
	version: number;
	teacher_count: number;
	lesson_count: number;
}
export interface SiteSettings {
	name: string;
	home_text: string;
	text_color: string;
	version: number;
}
export interface PublicSite {
	settings: SiteSettings;
}
export interface CourseImpact {
	id: number;
	title: string;
	subject_id: number;
	responsible: boolean;
}
