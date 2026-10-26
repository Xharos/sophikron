/** Course contracts and a deliberately small inline formatting language. */
import { loginDestination } from './loginRedirect.ts';
import { luminance } from './colors.ts';
export type LessonIcon =
	| 'book'
	| 'science'
	| 'calculator'
	| 'language'
	| 'history'
	| 'code'
	| 'school'
	| 'physics'
	| 'biology'
	| 'geology'
	| 'engineering'
	| 'astronomy'
	| 'statistics'
	| 'economics'
	| 'finance'
	| 'sociology'
	| 'geography'
	| 'philosophy'
	| 'literature'
	| 'ancient'
	| 'art'
	| 'music';
export type ElementKind = 'section' | 'subsection' | 'text' | 'youtube' | 'file' | 'table';
export interface LessonFile {
	id: number;
	original_name: string;
	extension: string;
	media_type: string;
	size_bytes: number;
	sha256: string;
}
export type ScheduleMode = 'inherit' | 'from' | 'range';
export interface LessonPerson {
	id: number;
	label: string;
	role: 'user' | 'kholleur' | 'teacher' | 'admin' | null;
	can_edit: boolean;
}
export interface LessonCard {
	id: number;
	title: string;
	description: string;
	icon: LessonIcon;
	color: string;
	creator: LessonPerson;
	responsible: LessonPerson;
	subject_id: number;
	subject_name: string;
	collaborators: LessonPerson[];
	can_open: boolean;
	can_edit: boolean;
	version: number;
	updated_at: string;
}

/** Show the current responsible teacher first, then collaborators grouped by teaching role. */
export function lessonTeam(lesson: Pick<LessonCard, 'responsible' | 'collaborators'>): {
	teachers: LessonPerson[];
	kholleurs: LessonPerson[];
} {
	const people = [
		...new Map(
			[lesson.responsible, ...lesson.collaborators].map((person) => [person.id, person])
		).values()
	];
	people.sort((first, second) =>
		first.id === lesson.responsible.id
			? -1
			: second.id === lesson.responsible.id
				? 1
				: first.label.localeCompare(second.label, 'fr')
	);
	return {
		teachers: people.filter((person) => person.role !== 'kholleur'),
		kholleurs: people.filter((person) => person.role === 'kholleur')
	};
}
export interface LessonPage {
	items: LessonCard[];
	total: number;
	offset: number;
	limit: number;
	can_create: boolean;
}
export interface LessonElement {
	id: number;
	parent_id: number | null;
	kind: ElementKind;
	position: number;
	title: string;
	body: string;
	schedule_mode: ScheduleMode;
	starts_on: string | null;
	ends_on: string | null;
	effective_starts_on: string | null;
	effective_ends_on: string | null;
	inherited_from: string | null;
	available: boolean;
	status: 'available' | 'scheduled' | 'expired';
	audience: 'students' | 'staff';
	effective_audience: 'students' | 'staff';
	table_rows: number;
	table_columns: string[];
	row_index: number | null;
	column_index: number | null;
	file: LessonFile | null;
}
export interface LessonAccess {
	promotion_id: number;
	identifier: string;
	year: number;
	color: string;
	is_active: boolean;
	starts_on: string;
	ends_on: string;
}
export interface LessonDetail extends LessonCard {
	can_view_statistics: boolean;
	can_manage_collaborators: boolean;
	can_transfer: boolean;
	staff_view: boolean;
	today: string;
	elements: LessonElement[];
	promotions: LessonAccess[];
	warnings: string[];
}
export interface LessonFields {
	title: string;
	description: string;
	subject_id: number;
}
export interface ElementFields {
	title: string;
	body: string;
	schedule_mode: ScheduleMode;
	starts_on: string | null;
	ends_on: string | null;
}
export const lessonIcons: { value: LessonIcon; label: string }[] = [
	{ value: 'book', label: 'Livre' },
	{ value: 'science', label: 'Sciences' },
	{ value: 'calculator', label: 'Mathématiques' },
	{ value: 'physics', label: 'Physique' },
	{ value: 'biology', label: 'Biologie' },
	{ value: 'geology', label: 'Géologie' },
	{ value: 'engineering', label: 'Sciences de l’ingénieur' },
	{ value: 'astronomy', label: 'Astronomie' },
	{ value: 'statistics', label: 'Statistiques' },
	{ value: 'economics', label: 'Économie' },
	{ value: 'finance', label: 'Finance' },
	{ value: 'sociology', label: 'Sociologie' },
	{ value: 'geography', label: 'Géographie' },
	{ value: 'philosophy', label: 'Philosophie' },
	{ value: 'literature', label: 'Lettres' },
	{ value: 'ancient', label: 'Latin et grec' },
	{ value: 'art', label: 'Histoire des arts' },
	{ value: 'music', label: 'Musique' },
	{ value: 'language', label: 'Langues' },
	{ value: 'history', label: 'Histoire' },
	{ value: 'code', label: 'Informatique' },
	{ value: 'school', label: 'Établissement' }
];
export const elementLabels: Record<ElementKind, string> = {
	section: 'Section',
	subsection: 'Sous-section',
	text: 'Texte',
	youtube: 'Vidéo YouTube',
	file: 'Document',
	table: 'Tableau de ressources'
};

/** Hide only the file's actual extension, preserving dots in author-selected titles. */
export function documentLabel(title: string, extension: string): string {
	const suffix = `.${extension}`;
	return title.length > suffix.length && title.toLowerCase().endsWith(suffix.toLowerCase())
		? title.slice(0, -suffix.length)
		: title;
}
export interface TextPart {
	text: string;
	bold: boolean;
	italic: boolean;
	colored: boolean;
}

/** Pair exact delimiters and render plain text segments, with no HTML interpretation. */
export function formattedText(value: string): TextPart[] {
	const tokens = value.split(/(\*{1,3}|==)/g);
	const stack: { marker: string; index: number }[] = [];
	const paired = new Set<number>();
	for (let index = 1; index < tokens.length; index += 2) {
		const marker = tokens[index];
		if (stack.at(-1)?.marker === marker) {
			paired.add(stack.pop()!.index);
			paired.add(index);
		} else stack.push({ marker, index });
	}
	let bold = false,
		italic = false,
		colored = false;
	const parts: TextPart[] = [];
	for (let index = 0; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (paired.has(index)) {
			if (token === '**' || token === '***') bold = !bold;
			if (token === '*' || token === '***') italic = !italic;
			if (token === '==') colored = !colored;
		} else if (token) parts.push({ text: token, bold, italic, colored });
	}
	return parts;
}

export interface TextBlock {
	level: number;
	parts: TextPart[];
}

/** Preserve formatting across lines while recognizing escaped-text section headings. */
export function formattedBlocks(value: string): TextBlock[] {
	const blocks: TextBlock[] = [{ level: 0, parts: [] }];
	for (const part of formattedText(value)) {
		for (const [index, text] of part.text.split('\n').entries()) {
			if (index) blocks.push({ level: 0, parts: [] });
			if (text) blocks.at(-1)!.parts.push({ ...part, text });
		}
	}
	for (const block of blocks) {
		const heading = /^(#{1,2})\s+(.+)$/.exec(block.parts.map((part) => part.text).join(''));
		if (!heading) continue;
		block.level = heading[1].length;
		let remaining = heading[0].length - heading[2].length;
		block.parts = block.parts.flatMap((part) => {
			const removed = Math.min(remaining, part.text.length);
			remaining -= removed;
			return removed < part.text.length ? [{ ...part, text: part.text.slice(removed) }] : [];
		});
	}
	return blocks;
}

/** Keep dates calendar-based instead of shifting midnight through the browser's timezone. */
export function lessonDate(value: string | null): string {
	if (!value) return '—';
	return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeZone: 'UTC' }).format(
		new Date(`${value}T12:00:00Z`)
	);
}

export function periodLabel(start: string | null, end: string | null): string {
	if (start && end) return `Du ${lessonDate(start)} au ${lessonDate(end)}`;
	if (start) return `À partir du ${lessonDate(start)}`;
	return 'Toute l’année';
}

/** Use a contrasting label on any validated teacher-selected course color. */
export function colorForeground(color: string): '#000000' | '#ffffff' {
	return luminance(color) > 0.179 ? '#000000' : '#ffffff';
}

/** Same-origin allowlisted transport; the server constructs all backend paths. */
export async function lessonCommand<T>(command: string, payload: object = {}): Promise<T> {
	const response = await fetch('/lessons/command', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ command, ...payload })
	});
	const data = await response.json();
	if (!response.ok) {
		if (response.status === 401)
			window.location.assign(
				loginDestination(window.location.pathname + window.location.search + window.location.hash)
			);
		if ([401, 403].includes(response.status))
			window.dispatchEvent(new Event('lesson-access-revoked'));
		throw new LessonError(response.status, data.message || 'La demande a échoué.');
	}
	return data as T;
}

export class LessonError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}
