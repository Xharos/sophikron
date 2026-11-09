import type { KholleWishes } from './kholleWishes';
import type { GeneratedSession } from './kholloscopeGeneration';
import type { TimetableYear } from './timetable';

export interface RevisionView {
	rooms?: { id: number; name: string; kholle_capacity: number }[];
	pending_publications?: {
		id: string;
		revision: string;
		effective_on: string;
		return_on?: string | null;
		can_rollback: boolean;
	}[];
	problems?: {
		kind: 'groups' | 'room_capacity' | 'teacher_archived' | 'memberships' | 'availability';
		message: string;
		calendar_id: number;
	}[];
	needs_recalculation?: boolean;
	source_revision: string;
	next_monday: string;
	published_sessions: GeneratedSession[];
	calendars: TimetableYear[];
	subjects: (KholleWishes['subjects'][number] & { required_service: number })[];
	branch: null | {
		id: string;
		revision: string;
		status: string;
		stale: boolean;
		effective_on: string;
		return_on?: string | null;
		subject_id: number;
		subject_ids?: number[];
		wishes: { subject_id?: number; user_id: number; sessions: number }[];
		allow_moves: boolean;
		rooms?: Record<number, number[]>;
		future_service: Record<number, Record<number, number>>;
		history_sessions: GeneratedSession[];
		closed: boolean;
		logs: string[];
		result: null | {
			merged: boolean;
			sessions: GeneratedSession[];
			changes: { before: GeneratedSession | null; after: GeneratedSession | null }[];
			quotas: {
				calendar_id: number;
				group: number;
				subject_id: number;
				acquired: number;
				remaining: number;
				total: number;
			}[];
		};
	};
}

export type RevisionDifference = {
	before: GeneratedSession | null;
	after: GeneratedSession | null;
};

/** Summarize equivalent recurring changes, retaining occurrence dates only as a range. */
export function groupedRevisionChanges(changes: RevisionDifference[]): {
	key: string;
	before: GeneratedSession | null;
	after: GeneratedSession | null;
	count: number;
	first: string;
	last: string;
}[] {
	const groups = new Map<
		string,
		{
			key: string;
			before: GeneratedSession | null;
			after: GeneratedSession | null;
			count: number;
			first: string;
			last: string;
		}
	>();
	const signature = (s: GeneratedSession | null): unknown =>
		s && [
			s.calendar_id,
			s.subject_id,
			s.group,
			new Date(s.day + 'T00:00:00Z').getUTCDay(),
			s.start,
			s.end,
			s.teacher_id,
			s.room_id
		];
	for (const change of changes) {
		const session = change.after ?? change.before;
		if (!session) continue;
		const offset =
			change.before && change.after
				? Date.parse(change.after.day) - Date.parse(change.before.day)
				: 0;
		const key = JSON.stringify([signature(change.before), signature(change.after), offset]);
		const day = session.day;
		const group = groups.get(key);
		if (group) {
			group.count++;
			if (day < group.first) group.first = day;
			if (day > group.last) group.last = day;
		} else groups.set(key, { key, ...change, count: 1, first: day, last: day });
	}
	return [...groups.values()].sort(
		(a, b) => a.first.localeCompare(b.first) || a.key.localeCompare(b.key)
	);
}

/** Check a civil Monday without interpreting a date-only input in the browser timezone. */
export function isRevisionMonday(value: string): boolean {
	if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
	const day = new Date(`${value}T00:00:00Z`);
	return (
		!Number.isNaN(day.valueOf()) &&
		day.toISOString().slice(0, 10) === value &&
		day.getUTCDay() === 1
	);
}

/** Distinguish student-visible slot changes from simple replacements. */
export function revisionChange(before: GeneratedSession | null, after: GeneratedSession): string {
	if (!before) return 'Ajout';
	if (before.day !== after.day || before.start !== after.start || before.end !== after.end)
		return 'Déplacement';
	return before.teacher_id !== after.teacher_id ? 'Remplacement' : 'Changement de salle';
}
