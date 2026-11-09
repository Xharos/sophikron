/** Private durable generation contracts; sessions do not expose real group membership. */
import type { TimetableYear } from './timetable';

export type RotationMode = 'fixed' | 'weekly' | 'cycle';
export interface KholloscopeCalendarView {
	run: null | {
		calendars?: TimetableYear[];
		result: null | { reference: string; quotas: { calendar_id: number }[] };
	};
}
export interface GenerationRules {
	rounding: 'none' | 'floor' | 'ceil';
	teacher_lunch: boolean;
	teacher_lunch_minutes: number;
	recovery_weeks: number;
	max_per_day: number;
	time_limit: number;
	preserve_locks: boolean;
	optimize: boolean;
	time_stability_percent: number;
	time_weekly_percent: number;
	time_rotation_percent: number;
	time_annual_percent: number;
}
export interface GeneratedSession {
	id: string;
	calendar_id: number;
	subject_id: number;
	teacher_id: number;
	room_id: number;
	day: string;
	start: number;
	end: number;
	original_day?: string;
	original_start?: number;
	locked?: boolean;
	phase?: number;
	group?: number;
}
export interface GroupAssignment {
	calendar_id: number;
	track: number;
	group: number;
}
export interface GenerationView {
	pending_publications?: { id: string; effective_on: string; return_on?: string | null }[];
	revision_state?: { conflicts: boolean; pending: boolean };
	source_revision: string;
	ready: boolean;
	run: null | {
		id: string;
		status: string;
		revision: string;
		stale: boolean;
		rules: GenerationRules;
		logs: string[];
		calendars?: TimetableYear[];
		result: null | {
			sessions: GeneratedSession[];
			template: GeneratedSession[];
			moved: number;
			applied: boolean;
			saved?: boolean;
			assignment_mode?: RotationMode;
			withdrawn?: { scope: 'future' | 'all'; removed: number; at: string };
			quotas: {
				calendar_id: number;
				subject_id: number;
				sessions: number;
				original_minutes: number;
				rounded: boolean;
				cycle_based?: boolean;
				min_sessions?: number;
				max_sessions?: number;
			}[];
			mappings: GroupAssignment[];
			reference: string;
			cycle_length?: number;
		};
	};
}
export interface GenerationGroups {
	rotation_adjustments?: number;
	assigned_sessions?: GeneratedSession[];
	mode?: RotationMode;
	schedule: (GeneratedSession & { track: number })[];
	revision: string;
	mappings: GroupAssignment[];
	calendars: { id: number; name: string; groups: number[]; tracks: number }[];
}
export const defaultGenerationRules: GenerationRules = {
	rounding: 'none',
	teacher_lunch: true,
	teacher_lunch_minutes: 55,
	recovery_weeks: 1,
	max_per_day: 2,
	time_limit: 900,
	preserve_locks: true,
	optimize: true,
	time_stability_percent: 5,
	time_weekly_percent: 20,
	time_rotation_percent: 70,
	time_annual_percent: 5
};

export const generationTimeStages = [
	{ key: 'time_stability_percent', label: 'Stabilité A/B' },
	{ key: 'time_weekly_percent', label: 'Répartition hebdomadaire' },
	{ key: 'time_rotation_percent', label: 'Horaires précoces et rotation' },
	{ key: 'time_annual_percent', label: 'Adaptation annuelle' }
] as const;

/** Sum stage percentages, treating cleared numeric inputs as zero. */
export function generationTimeTotal(rules: GenerationRules): number {
	return generationTimeStages.reduce((total, stage) => total + (rules[stage.key] || 0), 0);
}

export interface SessionFilters {
	calendar: number;
	teacher: number;
	subject: number;
	room: number;
	group: number;
}

/** Apply the same resource filters to the calendar and the changes list. */
export function matchesSession(session: GeneratedSession, filters: SessionFilters): boolean {
	return (
		(!filters.calendar || session.calendar_id === filters.calendar) &&
		(!filters.teacher || session.teacher_id === filters.teacher) &&
		(!filters.subject || session.subject_id === filters.subject) &&
		(!filters.room || session.room_id === filters.room) &&
		(!filters.group || session.group === filters.group)
	);
}

export interface ColloscopeRow {
	key: string;
	weekday: number;
	start: number;
	teacher: number;
	room: number;
	cells: Map<string, GeneratedSession[]>;
}

/** Group one promotion/subject's actual sessions by recurring slot, retaining empty weeks. */
export function colloscopeRows(
	sessions: GeneratedSession[],
	teachingWeeks: string[] = []
): { weeks: string[]; rows: ColloscopeRow[] } {
	const rows = new Map<string, ColloscopeRow>();
	const weeks = new Set(teachingWeeks);
	for (const session of sessions) {
		if (session.group === undefined) continue;
		const date = new Date(`${session.day}T12:00:00Z`);
		const weekday = (date.getUTCDay() + 6) % 7;
		date.setUTCDate(date.getUTCDate() - weekday);
		const week = date.toISOString().slice(0, 10);
		weeks.add(week);
		const key = `${weekday}/${session.start}/${session.teacher_id}/${session.room_id}`;
		const row = rows.get(key) ?? {
			key,
			weekday,
			start: session.start,
			teacher: session.teacher_id,
			room: session.room_id,
			cells: new Map<string, GeneratedSession[]>()
		};
		const values = row.cells.get(week) ?? [];
		values.push(session);
		values.sort((a, b) => (a.group ?? 0) - (b.group ?? 0));
		row.cells.set(week, values);
		rows.set(key, row);
	}
	return {
		weeks: [...weeks].sort(),
		rows: [...rows.values()].sort(
			(a, b) =>
				a.weekday - b.weekday || a.start - b.start || a.teacher - b.teacher || a.room - b.room
		)
	};
}

/** Require a complete bijection, rejecting duplicates and foreign group numbers locally. */
export function validGroupMapping(choices: GenerationGroups, mappings: GroupAssignment[]): boolean {
	return (
		mappings.length === choices.calendars.reduce((sum, c) => sum + c.tracks, 0) &&
		choices.calendars.every((c) => {
			const rows = mappings.filter((m) => m.calendar_id === c.id);
			return (
				rows.length === c.tracks &&
				new Set(rows.map((m) => m.track)).size === c.tracks &&
				new Set(rows.map((m) => m.group)).size === c.groups.length &&
				rows.every((m) => m.track >= 1 && m.track <= c.tracks && c.groups.includes(m.group))
			);
		})
	);
}
