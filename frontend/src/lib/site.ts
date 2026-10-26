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
	holiday_color: string;
	version: number;
}
export interface Timeline {
	id: number;
	name: string;
	starts_on: string;
	ends_on: string;
	color: string;
	version: number;
}
export interface TimelineEvent extends Timeline {
	kind: 'holiday' | 'oral' | 'written' | 'school' | 'other';
	timeline_ids: number[];
}
export interface PublicSite {
	settings: SiteSettings;
	timelines: Timeline[];
	events: TimelineEvent[];
	today: string;
}
export interface CourseImpact {
	id: number;
	title: string;
	subject_id: number;
	responsible: boolean;
}
export const eventLabels: Record<TimelineEvent['kind'], string> = {
	holiday: 'Vacances',
	oral: 'Oraux',
	written: 'Écrits',
	school: 'École',
	other: 'Autre'
};

/** Compare calendar days in Paris without depending on the visitor's timezone. */
export function parisDay(now: Date = new Date()): string {
	const parts = new Intl.DateTimeFormat('en-CA', {
		timeZone: 'Europe/Paris',
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	}).formatToParts(now);
	return ['year', 'month', 'day']
		.map((name) => parts.find((part) => part.type === name)!.value)
		.join('-');
}

/** Inclusive day ranges reach completion at the end of the last day. */
export function timelineProgress(start: string, end: string, today: string): number {
	const first = Date.parse(start),
		last = Date.parse(end),
		current = Date.parse(today);
	return Math.max(0, Math.min(100, ((current - first) / (last - first + 86400000)) * 100));
}

/** Locate the inclusive end of an event without creating a date beyond year 9999. */
export function timelineEventEnd(start: string, end: string, eventEnd: string): number {
	return Math.max(
		0,
		Math.min(
			100,
			((Date.parse(eventEnd) + 86400000 - Date.parse(start)) /
				(Date.parse(end) - Date.parse(start) + 86400000)) *
				100
		)
	);
}

/** Count Monday–Friday days in an inclusive UTC range without DST effects. */
function weekdays(first: number, last: number): number {
	const days = Math.max(0, Math.round((last - first) / 86400000) + 1);
	let count = Math.floor(days / 7) * 5;
	const weekday = new Date(first).getUTCDay();
	for (let index = 0; index < days % 7; index++) {
		const current = (weekday + index) % 7;
		if (current !== 0 && current !== 6) count++;
	}
	return count;
}
/** Calculate inclusive calendar/teaching days; overlapping holidays are counted once. */
export function timelineStats(
	bar: Timeline,
	events: TimelineEvent[],
	today: string
): {
	totalDays: number;
	remainingDays: number;
	progress: number;
	totalWorkingDays: number;
	remainingWorkingDays: number;
} {
	const first = Date.parse(bar.starts_on),
		last = Date.parse(bar.ends_on);
	const current = Math.max(first, Date.parse(today));
	const holidays = events
		.filter((event) => event.kind === 'holiday' && event.timeline_ids.includes(bar.id))
		.map((event) => [
			Math.max(first, Date.parse(event.starts_on)),
			Math.min(last, Date.parse(event.ends_on))
		])
		.filter(([start, end]) => start <= end)
		.sort((left, right) => left[0] - right[0]);
	const merged: number[][] = [];
	for (const [start, end] of holidays) {
		const previous = merged.at(-1);
		if (previous && start <= previous[1] + 86400000) previous[1] = Math.max(previous[1], end);
		else merged.push([start, end]);
	}
	const totalDays = Math.round((last - first) / 86400000) + 1;
	return {
		totalDays,
		remainingDays: Math.max(0, Math.round((last - current) / 86400000) + 1),
		progress: timelineProgress(bar.starts_on, bar.ends_on, today),
		totalWorkingDays:
			weekdays(first, last) - merged.reduce((sum, [start, end]) => sum + weekdays(start, end), 0),
		remainingWorkingDays:
			weekdays(current, last) -
			merged.reduce((sum, [start, end]) => sum + weekdays(Math.max(current, start), end), 0)
	};
}
/** Split an inclusive bar into calendar months, keeping partial months proportional. */
export function timelineMonths(
	start: string,
	end: string
): { key: string; label: string; title: string; width: number }[] {
	const first = Date.parse(start),
		last = Date.parse(end) + 86400000;
	const date = new Date(first);
	date.setUTCDate(1);
	const formatter = new Intl.DateTimeFormat('fr-FR', { month: 'short', timeZone: 'UTC' });
	const result = [];
	while (date.getTime() < last) {
		const month = date.getTime();
		const label = formatter.format(date);
		const year = date.getUTCFullYear();
		date.setUTCMonth(date.getUTCMonth() + 1);
		result.push({
			key: String(month),
			label,
			title: label + ' ' + year,
			width: ((Math.min(last, date.getTime()) - Math.max(first, month)) / (last - first)) * 100
		});
	}
	return result;
}

/** Keep individual event identities while grouping every holiday under one legend entry. */
export function calendarLegend(
	events: TimelineEvent[],
	holidayColor: string
): {
	key: string;
	label: string;
	color: string;
	event?: TimelineEvent;
}[] {
	const entries: { key: string; label: string; color: string; event?: TimelineEvent }[] = [];
	let hasHolidays = false;
	for (const event of events) {
		if (event.kind === 'holiday') {
			if (!hasHolidays) entries.push({ key: 'holiday', label: 'Vacances', color: holidayColor });
			hasHolidays = true;
		} else entries.push({ key: 'event-' + event.id, label: event.name, color: event.color, event });
	}
	return entries;
}
