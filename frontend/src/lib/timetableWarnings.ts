/** Resolve warning targets using stable source identities rather than parsing translated messages. */
import {
	crossCalendarTeacherConflicts,
	teacherAvailabilityDetails,
	timetableConflictDetails,
	type TimetableBoard,
	type TimetableBlock,
	type TimetableIssue,
	type TimetableEvent,
	type TimetableYear
} from './timetable.ts';

export interface DiagnosticEntry extends TimetableIssue {
	identity?: string;
	events?: TimetableEvent[];
	change?: 'added' | 'removed' | 'changed';
	previous?: DiagnosticEntry;
}

/** Compose the same structured checks for the board and for an unsaved proposal. */
export function timetableDiagnostics(
	board: TimetableBoard,
	today: string,
	focus?: {
		event: TimetableEvent | null;
		block: TimetableBlock | null;
		scope: 'one' | 'future';
		originalSeries: string[];
	}
): DiagnosticEntry[] {
	const events = focus
		? board.events.filter((event) => {
				if (!focus.event) return true;
				const day = event.start.slice(0, 10);
				const firstDay = [
					focus.event.start.slice(0, 10),
					focus.block?.starts_on ?? focus.event.source_date
				].sort()[0];
				return focus.scope === 'future'
					? day >= firstDay
					: [focus.event.start.slice(0, 10), focus.block?.starts_on].includes(day);
			})
		: board.events;
	const warnings = [
		...timetableConflictDetails(events, board.groups ?? [], today),
		...crossCalendarTeacherConflicts(events, board.teacher_commitments ?? [], today),
		...teacherAvailabilityDetails(
			events,
			board.availability ?? [],
			today,
			board.years[0]?.school_year
		)
	].filter(
		(warning) =>
			!focus ||
			warning.events.some(
				(event) =>
					event.series_id === focus.event?.series_id ||
					(focus.event?.conflict_key && event.conflict_key === focus.event.conflict_key) ||
					!focus.originalSeries.includes(event.series_id)
			)
	);
	const aliases = new Set(
		focus
			? board.years
					.flatMap((year) => year.series)
					.filter(
						(series) =>
							series.id === focus.event?.series_id || !focus.originalSeries.includes(series.id)
					)
					.flatMap((series) => [series.id, series.lineage])
			: []
	);
	if (focus?.event) {
		aliases.add(focus.event.series_id);
		if (focus.event.conflict_key) aliases.add(focus.event.conflict_key);
	}
	return [
		...(board.issues ?? []),
		...warnings.map((warning) => ({
			...warning,
			severity: warning.severity ?? ('warning' as const),
			identity: warning.code.replace(/[a-f0-9]{32}/g, (value) =>
				aliases.has(value) ? 'edited' : value
			)
		}))
	];
}

/** Compare logical checks independently of newly generated recurrence node identifiers. */
export function diagnosticChanges(
	before: DiagnosticEntry[],
	after: DiagnosticEntry[]
): DiagnosticEntry[] {
	const key = (entry: DiagnosticEntry): string => entry.identity ?? entry.code;
	const signature = (entry: DiagnosticEntry): string =>
		JSON.stringify([entry.message, entry.severity, entry.groups, entry.cycles]);
	const group = (entries: DiagnosticEntry[]): Map<string, DiagnosticEntry> =>
		new Map(entries.map((entry) => [key(entry), entry]));
	const previous = group(before),
		next = group(after);
	const changes: DiagnosticEntry[] = [];
	for (const [id, entry] of next) {
		const old = previous.get(id);
		if (!old) changes.push({ ...entry, change: 'added' });
		else if (signature(entry) !== signature(old))
			changes.push({ ...entry, change: 'changed', previous: old });
	}
	for (const [id, entry] of previous)
		if (!next.has(id)) changes.push({ ...entry, change: 'removed' });
	return changes.sort(
		(a, b) =>
			Number(b.severity === 'critical' && b.change !== 'removed') -
			Number(a.severity === 'critical' && a.change !== 'removed')
	);
}

export interface WarningEventTarget {
	event: TimetableEvent;
	recurrenceKey?: string;
}

/** Keep independent exceptions dated and group unchanged recurring assignments by lineage. */
export function warningEventTarget(event: TimetableEvent, year: TimetableYear): WarningEventTarget {
	const source = year.series.find((series) => series.id === event.series_id);
	const exception =
		event.is_exception ?? Object.hasOwn(source?.exceptions ?? {}, event.source_date);
	return { event, ...(!exception && source?.interval ? { recurrenceKey: source.lineage } : {}) };
}
/** Merge split segments and recurring references while retaining separate dated exceptions. */
export function uniqueWarningTargets(targets: WarningEventTarget[]): WarningEventTarget[] {
	const unique = new Map<string, WarningEventTarget>();
	for (const target of [...targets].sort((a, b) => a.event.start.localeCompare(b.event.start))) {
		const key = target.recurrenceKey
			? 'recurrence-' + target.event.year_id + '-' + target.recurrenceKey
			: target.event.year_id + '-' + target.event.series_id + '-' + target.event.source_date;
		if (!unique.has(key)) unique.set(key, target);
	}
	return [...unique.values()];
}

/** Format the complete logical session range in school wall-clock time, including seconds if needed. */
export function warningEventWhen(target: WarningEventTarget, year: TimetableYear): string {
	const time = (seconds: number): string => {
		const base = `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}`;
		return seconds % 60 ? `${base}:${String(seconds % 60).padStart(2, '0')}` : base;
	};
	const event = target.event;
	const seconds = (value: string): number => {
		const [h, m, s = 0] = value.slice(11, 19).split(':').map(Number);
		return h * 3600 + m * 60 + s;
	};
	const start = event.start_time ?? year.slots[event.start_slot]?.[0] ?? seconds(event.start);
	const end =
		event.end_time ??
		year.slots[event.start_slot + event.duration_slots - 1]?.[1] ??
		seconds(event.end);
	const day = new Date(`${event.start.slice(0, 10)}T12:00:00Z`);
	const label = new Intl.DateTimeFormat('fr-FR', {
		timeZone: 'UTC',
		weekday: 'long',
		day: 'numeric',
		month: 'long',
		year: 'numeric'
	}).format(day);
	return `${label} · ${time(start)}–${time(end)}`;
}

/** Prefer the session's teaching role for dual-role accounts, never their administrator role. */
export function warningTeachingRole(kind: TimetableEvent['kind'], roles: string[]): string | null {
	if (kind === 'kholle' && roles.includes('kholleur')) return 'kholleur';
	if (roles.includes('teacher')) return 'teacher';
	return roles.includes('kholleur') ? 'kholleur' : null;
}
