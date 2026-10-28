/** Resolve warning targets using stable source identities rather than parsing translated messages. */
import type { TimetableEvent, TimetableYear, WeeklyBlock } from './timetable';

export interface WarningEventTarget {
	event: TimetableEvent;
	templateKey: string | null;
	recurrenceKey?: string;
}

/** Exceptions and independent recurring series stay dated; current template blocks open weekly editing. */
export function warningEventTarget(
	event: TimetableEvent,
	year: TimetableYear,
	blocks: WeeklyBlock[],
	templateMode: boolean
): WarningEventTarget {
	if (templateMode && blocks.some((block) => block.key === event.series_id))
		return { event, templateKey: event.series_id };
	const source = year.series.find((series) => series.id === event.series_id);
	const key = event.template_key ?? source?.template_key;
	const exception =
		event.is_exception ?? Object.hasOwn(source?.exceptions ?? {}, event.source_date);
	return {
		event,
		templateKey: !exception && key && blocks.some((block) => block.key === key) ? key : null,
		...(!exception && source && source.interval > 0 ? { recurrenceKey: source.lineage } : {})
	};
}

/** Keep one entry per template block or dated occurrence, merging recess-split segments. */
export function uniqueWarningTargets(targets: WarningEventTarget[]): WarningEventTarget[] {
	const unique = new Map<string, WarningEventTarget>();
	for (const target of [...targets].sort((a, b) => a.event.start.localeCompare(b.event.start))) {
		const key = target.templateKey
			? `template-${target.templateKey}`
			: target.recurrenceKey
				? `recurrence-${target.event.year_id}-${target.recurrenceKey}`
				: `${target.event.year_id}-${target.event.series_id}-${target.event.source_date}`;
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
	const start = year.slots[event.start_slot]?.[0] ?? seconds(event.start);
	const end = year.slots[event.start_slot + event.duration_slots - 1]?.[1] ?? seconds(event.end);
	const day = new Date(`${event.start.slice(0, 10)}T12:00:00Z`);
	const label = new Intl.DateTimeFormat('fr-FR', {
		timeZone: 'UTC',
		weekday: 'long',
		...(target.templateKey
			? {}
			: { day: 'numeric' as const, month: 'long' as const, year: 'numeric' as const })
	}).format(day);
	return `${label} · ${time(start)}–${time(end)}`;
}

/** Prefer the session's teaching role for dual-role accounts, never their administrator role. */
export function warningTeachingRole(kind: TimetableEvent['kind'], roles: string[]): string | null {
	if (kind === 'kholle' && roles.includes('kholleur')) return 'kholleur';
	if (roles.includes('teacher')) return 'teacher';
	return roles.includes('kholleur') ? 'kholleur' : null;
}
