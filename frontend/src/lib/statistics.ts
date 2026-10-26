/** Shared chart contracts, palette and pure geometry; charts never invent unavailable history. */
export type StatisticsPeriod = 'day' | 'week' | 'month';
export interface Breakdown {
	label: string;
	value: number;
	count: number;
	id: number | null;
}
export interface Statistics {
	scope: 'admin' | 'author' | 'course';
	period: StatisticsPeriod;
	timestamps: string[];
	generated_at: string;
	attempts_since: string | null;
	series: Record<string, number[]>;
	totals: Record<string, number>;
	storage: {
		files: number;
		bytes: number;
		quota_bytes: number;
		reserved_bytes: number;
		physical_bytes: number | null;
		temporary_bytes: number | null;
		pending_deletions: number | null;
		formats: Breakdown[];
	};
	accounts: Breakdown[];
	roles: Breakdown[];
	promotions: Breakdown[];
	promotion_staff: Breakdown[];
	subjects: Breakdown[];
	popular: Breakdown[];
	courses: Breakdown[];
}
export interface ChartSeries {
	key: string;
	label: string;
	values: number[];
	color: string;
}
export const chartPalette = [
	'#244bc1',
	'#2d8b72',
	'#d08a2b',
	'#9c60b6',
	'#d1606a',
	'#517c91',
	'#84863d',
	'#a15d37'
];
export function byteLabel(value: number): string {
	const units = ['o', 'Kio', 'Mio', 'Gio', 'Tio'];
	const index =
		value > 0 ? Math.max(0, Math.min(4, Math.floor(Math.log(value) / Math.log(1024)))) : 0;
	return `${(value / 1024 ** index).toLocaleString('fr-FR', { maximumFractionDigits: index ? 1 : 0 })} ${units[index]}`;
}
/** Fit the scale to the visible maximum, with a nonzero fallback for empty charts. */
export function chartMaximum(series: ChartSeries[]): number {
	return Math.max(0, ...series.flatMap((item) => item.values)) || 1;
}
export function linePoints(values: number[], maximum: number): string {
	return values
		.map(
			(value, index) =>
				`${44 + (index / Math.max(1, values.length - 1)) * 466},${184 - (value / maximum) * 160}`
		)
		.join(' ');
}

/** Keep pointer and keyboard targets within the plot, including one- and two-point charts. */
export function pointBounds(index: number, count: number): { x: number; width: number } {
	if (count <= 1) return { x: 44, width: 466 };
	const left = 44 + Math.max(0, (index - 0.5) / (count - 1)) * 466;
	const right = 44 + Math.min(1, (index + 0.5) / (count - 1)) * 466;
	return { x: left, width: right - left };
}
export function timeLabels(
	timestamps: string[],
	period: StatisticsPeriod,
	detail = false
): string[] {
	return timestamps.map((timestamp) =>
		new Intl.DateTimeFormat('fr-FR', {
			timeZone: 'Europe/Paris',
			...(period === 'day'
				? {
						hour: '2-digit',
						minute: '2-digit',
						...(detail ? { timeZoneName: 'short' as const } : {})
					}
				: { day: 'numeric', month: 'short' })
		}).format(new Date(timestamp))
	);
}
export function breakdownSeries(items: Breakdown[]): ChartSeries[] {
	return items.map((item, index) => ({
		key: item.label,
		label: item.label,
		values: [item.value],
		color: chartPalette[index % chartPalette.length]
	}));
}
