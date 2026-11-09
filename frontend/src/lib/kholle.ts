/** Exact clock minutes per group, independent of pedagogical session lengths. */
export interface KholleSettings {
	start: string;
	end: string;
	subjects: { subject_id: number; minutes: number }[];
}
export interface KholleState {
	published?: boolean;
	group_size?: number | null;
	settings: KholleSettings | null;
	revision: string;
	year_revision: string;
	group_count: number;
	weeks: { start: string; end: string; number: number; days: number; eligible: boolean }[];
}

/** Convert the group's weekly minutes using the promotion's configured group size. */
export function khollePupilMinutes(
	minutes: number,
	weeks: number,
	groupSize: number | null | undefined
): number | null {
	return weeks > 0 && groupSize && groupSize > 0 ? minutes / weeks / groupSize : null;
}

/** Accept French and dot decimals only when they describe a whole number of minutes. */
export function kholleMinutes(value: string): number | null {
	if (!/^\d+(?:[.,]\d+)?$/.test(value.trim())) return null;
	const minutes = Number(value.trim().replace(',', '.')) * 60;
	return Number.isFinite(minutes) &&
		minutes <= 600000 &&
		Math.abs(minutes - Math.round(minutes)) < 1e-7
		? Math.round(minutes)
		: null;
}

/** Describe a duration without interpreting decimal hours as clock minutes. */
export function kholleDuration(minutes: number): string {
	const remainder = Math.round(minutes % 60);
	return `${Math.floor(minutes / 60)}h${remainder ? String(remainder).padStart(2, '0') : ''}`;
}

/** Aggregate each subject once per group; excluded weeks never dilute the average. */
export function kholleLoad(
	minutes: number[],
	groups: number,
	weeks: number
): {
	perGroup: number;
	total: number;
	weekly: number | null;
} {
	const perGroup = minutes.reduce((sum, value) => sum + value, 0);
	const total = perGroup * groups;
	return { perGroup, total, weekly: weeks > 0 ? total / 60 / weeks : null };
}
