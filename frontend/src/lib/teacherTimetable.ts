/** Teaching-only contracts and hour totals; availability is independent of session audiences. */
import type {
	AvailabilityRange,
	TimetableEvent,
	TimetableSettings,
	TimetableTeacher
} from './timetable';

export interface TeacherCatalog {
	administrator: boolean;
	today: string;
	teachers: TimetableTeacher[];
	subjects: { id: number; name: string; color: string }[];
	years: { school_year: number; settings: TimetableSettings; slots: [number, number][] }[];
}

export interface TeacherPattern {
	teacher_id: number;
	revision: string | null;
	default: boolean;
	ranges: AvailabilityRange[];
}

export interface TeacherBoard {
	availability: TeacherPattern[];
	events: TimetableEvent[];
	occupied_ranges?: AvailabilityRange[];
}

/** Keep a teacher's color stable across subject folders, selections and school years. */
export function teacherColor(id: number): string {
	return ['#244BC1', '#A34E18', '#2E8B57', '#9747BB', '#C03654', '#087E8B', '#786014'][id % 7];
}

/** Keep the teacher's hue while giving each calendar a stable darker shade. */
export function teacherCalendarColor(teacherId: number, calendarId: number): string {
	const base = teacherColor(teacherId);
	const shade = 0.55 + ((((calendarId * 0.618033988749895) % 1) + 1) % 1) * 0.45;
	return (
		'#' +
		[1, 3, 5]
			.map((index) =>
				Math.round(Number.parseInt(base.slice(index, index + 2), 16) * shade)
					.toString(16)
					.padStart(2, '0')
			)
			.join('')
	);
}

/** Ctrl toggles individual teachers; selecting a subject folder selects its complete roster. */
export function selectTeachers(current: number[], targets: number[], additive: boolean): number[] {
	if (!additive) return [...targets];
	const remove = targets.every((id) => current.includes(id));
	return remove
		? current.filter((id) => !targets.includes(id))
		: [...new Set([...current, ...targets])];
}

export interface TeacherHours {
	subjectId: number | null;
	course: number;
	td: number;
	tp: number;
	kholle: number;
	total: number;
}

/** Count actual assigned half-sessions, once per segment, without pupil audience weighting. */
export function teacherSubjectHours(
	events: TimetableEvent[],
	sessionMinutes: number
): TeacherHours[] {
	const result = new Map<number | null, TeacherHours>();
	const seen = new Set<string>();
	for (const event of events) {
		if (seen.has(event.id)) continue;
		seen.add(event.id);
		const row = result.get(event.subject_id) ?? {
			subjectId: event.subject_id,
			course: 0,
			td: 0,
			tp: 0,
			kholle: 0,
			total: 0
		};
		const minutes = (Date.parse(event.end) - Date.parse(event.start)) / 60000;
		const duration = event.session_minutes ?? sessionMinutes;
		const hours = minutes / (duration >= 55 && duration <= 65 ? duration : 60);
		row[event.kind] += hours;
		row.total += hours;
		result.set(event.subject_id, row);
	}
	return [...result.values()].sort(
		(a, b) => b.total - a.total || (a.subjectId ?? 0) - (b.subjectId ?? 0)
	);
}
