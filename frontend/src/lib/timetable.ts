/** Audience-scoped timetable contracts; persisted times are seconds after midnight. */
export interface TimetableSettings {
	start: string;
	end: string;
	day_start: number;
	day_end: number;
	session_minutes: number;
	saturday: boolean;
	lunch_start?: number;
	lunch_end?: number;
	breaks: { start: number; end: number }[];
	holidays: { name: string; start: string; end: string }[];
}
export interface AnnualSubjectHours {
	subject_id: number | null;
	course: number;
	td: number;
	tp: number;
	kholle: number;
	total: number;
	weekly: { course: number; td: number; tp: number; kholle: number; total: number };
}
export interface TimetableBlock {
	starts_on: string;
	start_slot: number;
	duration_slots: number;
	start_time?: number | null;
	end_time?: number | null;
	subject_id: number | null;
	teacher_id: number | null;
	room_id: number | null;
	kind: 'course' | 'td' | 'tp' | 'kholle';
	title: string;
	interval: 0 | 1 | 2 | 3;
	until: string | null;
	target_kind?: 'promotion' | 'halves' | 'thirds' | 'kholles' | 'custom' | 'student';
	target_number?: number | null;
	target_user_id?: number | null;
}
export interface TimetableSeries extends TimetableBlock {
	id: string;
	lineage: string;
	exceptions: Record<string, Omit<TimetableBlock, 'interval' | 'until'> | null>;
}
export interface TimetableEvent {
	start_time?: number | null;
	end_time?: number | null;
	id: string;
	series_id: string;
	conflict_key?: string;
	is_exception?: boolean;
	school_year?: number;
	session_minutes?: number;
	source_date: string;
	start: string;
	end: string;
	start_slot: number;
	duration_slots: number;
	subject_id: number | null;
	teacher_id: number | null;
	room_id: number | null;
	kind: TimetableBlock['kind'];
	title: string;
	audience_label?: string;
	calendar_label?: string;
	color: string;
	teacher: string;
	teacher_roles?: string[];
	teacher_available?: boolean;
	room: string;
	calendar_id: number;
	promotion_id: number | null;
	year_id: number;
	target_kind?: TimetableBlock['target_kind'];
	target_number?: number | null;
	target_user_id?: number | null;
}
export interface TimetableYear {
	id: number;
	calendar_id: number;
	school_year: number;
	settings: TimetableSettings;
	revision: string | null;
	slots: [number, number][];
	weeks: Record<string, number>;
	series: TimetableSeries[];
	hours?: AnnualSubjectHours[];
}
export interface TimetableAgenda {
	id: number;
	name: string;
	promotion_id: number | null;
	revision: string | null;
	is_paused?: boolean;
	is_archived?: boolean;
	years: { id: number; school_year: number; revision: string | null }[];
}
export interface TimetableCatalog {
	administrator: boolean;
	today: string;
	calendars: TimetableAgenda[];
	promotions: { id: number; name: string }[];
	teachers: TimetableTeacher[];
	subjects: { id: number; name: string; color: string }[];
	rooms: { id: number; name: string; revision?: string }[];
	common_years?: CommonTimetableYear[];
}

export interface TimetableTeacher {
	id: number;
	name: string;
	subject_ids?: number[];
	roles?: string[];
}
export interface TimetableBoard {
	years: TimetableYear[];
	events: TimetableEvent[];
	members: TimetableMember[];
	groups?: TimetableGroup[];
	warnings: string[];
	availability?: { teacher_id: number; school_year: number; ranges: AvailabilityRange[] }[];
	issues?: TimetableIssue[];
	calendars?: Pick<
		TimetableAgenda,
		'id' | 'name' | 'promotion_id' | 'revision' | 'is_paused' | 'is_archived'
	>[];
	teacher_commitments?: TeacherCommitment[];
}

export interface TeacherCommitment {
	teacher_id: number;
	calendar_id: number;
	calendar_label: string;
	year_id: number;
	series_id: string;
	conflict_key: string;
	source_date: string;
	start: string;
	end: string;
}

export interface TimetableIssue {
	code: string;
	severity: 'warning' | 'critical' | 'info';
	message: string;
	teacher_id?: number;
	subject_id?: number | null;
	family?: string;
	kind?: TimetableBlock['kind'];
	groups?: { label: string; hours: number }[];
	cycles?: number[];
}

export interface TimetableWarning {
	code: string;
	message: string;
	summary: string;
	events: TimetableEvent[];
	severity?: 'warning' | 'critical';
}

export interface CommonTimetableYear {
	school_year: number;
	revision: string;
	used: boolean;
}

/** Academic labels change on September 1, independently of individual teaching dates. */
export function currentSchoolYear(today: string): number {
	return Number(today.slice(0, 4)) - (Number(today.slice(5, 7)) < 9 ? 1 : 0);
}

/** Prefer the current label, then the nearest future label, then the most recent past label. */
export function preferredSchoolYear(years: { school_year: number }[], today: string): number {
	const current = currentSchoolYear(today);
	const labels = years.map((year) => year.school_year).sort((a, b) => a - b);
	return labels.find((year) => year >= current) ?? labels.at(-1) ?? 0;
}
export interface TimetableMember {
	id: number;
	name: string;
	roles: string[];
	promotion_ids: number[];
	assignments?: { promotion_id: number; kind: string; number: number }[];
}
export interface TimetableGroup {
	promotion_id: number;
	kind: 'halves' | 'thirds' | 'kholles' | 'custom';
	name?: string;
	is_active?: boolean;
	number: number;
	student_ids: number[];
}
export interface TimetableNode {
	key: string;
	label: string;
	kind: NonNullable<TimetableBlock['target_kind']>;
	number?: number;
	userId?: number;
	studentIds: number[];
	children: TimetableNode[];
}

/** Show each pupil under every assigned partition so name searches reveal all their groups. */
export function timetableTree(
	name: string,
	promotionId: number,
	members: TimetableMember[],
	groups: TimetableGroup[]
): TimetableNode {
	const pupils = members.filter(
		(member) => member.roles.includes('user') && member.promotion_ids.includes(promotionId)
	);
	const partitions = groups.filter(
		(group) => group.promotion_id === promotionId && group.is_active !== false
	);
	const root: TimetableNode = {
		key: 'promotion',
		label: name,
		kind: 'promotion',
		studentIds: pupils.map((pupil) => pupil.id),
		children: []
	};
	const priority = ['kholles', 'thirds', 'halves'].find((kind) =>
		partitions.some((group) => group.kind === kind)
	);
	const pupilNode = (pupil: TimetableMember): TimetableNode => ({
		key: `student-${pupil.id}`,
		label: pupil.name,
		kind: 'student',
		userId: pupil.id,
		studentIds: [pupil.id],
		children: []
	});
	for (const kind of ['halves', 'thirds', 'kholles', 'custom']) {
		for (const group of partitions
			.filter((item) => item.kind === kind)
			.sort((a, b) => a.number - b.number)) {
			const label =
				kind === 'custom'
					? (group.name ?? 'Groupe personnalisé')
					: kind === 'kholles'
						? `Khôlle ${String(group.number).padStart(3, '0')}`
						: `${kind === 'halves' ? 'Demi-groupe' : 'Tiers de groupe'} ${String.fromCharCode((kind === 'halves' ? 64 : 87) + group.number)}`;
			root.children.push({
				key: `${kind}-${group.number}`,
				label,
				kind: group.kind,
				number: group.number,
				studentIds: group.student_ids,
				children: pupils.filter((pupil) => group.student_ids.includes(pupil.id)).map(pupilNode)
			});
		}
	}
	const placed = new Set(
		root.children.flatMap((node) => node.children.flatMap((child) => child.studentIds))
	);
	const remaining = pupils.filter((pupil) => !placed.has(pupil.id));
	if (!priority && !partitions.some((group) => group.kind === 'custom'))
		root.children = remaining.map(pupilNode);
	else if (remaining.length)
		root.children.push({
			key: 'unassigned',
			label: 'Élèves non affectés',
			kind: 'promotion',
			studentIds: remaining.map((pupil) => pupil.id),
			children: remaining.map(pupilNode)
		});
	return root;
}

/** Match groups by their actual recipients, including intersecting partitions. */
export function nodeReceives(
	event: TimetableEvent,
	node: TimetableNode,
	members: TimetableMember[]
): boolean {
	if (node.key === 'promotion' || !event.target_kind || event.target_kind === 'promotion')
		return true;
	return members.some(
		(member) =>
			node.studentIds.includes(member.id) &&
			(event.target_kind === 'student'
				? member.id === event.target_user_id
				: member.assignments?.some(
						(group) =>
							group.promotion_id === event.promotion_id &&
							group.kind === event.target_kind &&
							group.number === event.target_number
					))
	);
}

export const blockKinds: Record<TimetableBlock['kind'], string> = {
	course: 'Cours',
	td: 'TD',
	tp: 'TP',
	kholle: 'Khôlle'
};

/** Name the session's recipients without resolving or exposing individual pupil identities. */
export function timetableAudienceLabel(
	event: Pick<TimetableEvent, 'target_kind' | 'target_number' | 'audience_label'>
): string {
	if (event.audience_label) return event.audience_label;
	switch (event.target_kind) {
		case 'halves':
			return event.target_number
				? `Demi-groupe ${String.fromCharCode(64 + event.target_number)}`
				: 'Demi-groupe';
		case 'thirds':
			return event.target_number
				? `Tiers de groupe ${String.fromCharCode(87 + event.target_number)}`
				: 'Tiers de groupe';
		case 'kholles':
			return event.target_number
				? `Groupe de khôlle ${String(event.target_number).padStart(3, '0')}`
				: 'Groupe de khôlle';
		case 'student':
			return 'Séance individuelle';
		case 'custom':
			return 'Groupe personnalisé';
		default:
			return 'Classe entière';
	}
}

/** Treat 55–65 minute teaching sessions as one pedagogical hour, including half-sessions. */
export function teachingHours(durationSlots: number, sessionMinutes: number): number {
	return (
		(durationSlots / 2) * (sessionMinutes >= 55 && sessionMinutes <= 65 ? 1 : sessionMinutes / 60)
	);
}

/** Keep subject specialists first and French alphabetical ordering within both groups. */
export function orderedTimetableTeachers(
	teachers: TimetableTeacher[],
	subjectId: number | null,
	kind?: TimetableBlock['kind']
): TimetableTeacher[] {
	return teachers
		.filter(
			(teacher) => kind === undefined || kind === 'kholle' || teacher.roles?.includes('teacher')
		)
		.sort(
			(left, right) =>
				Number(subjectId !== null && (right.subject_ids?.includes(subjectId) ?? false)) -
					Number(subjectId !== null && (left.subject_ids?.includes(subjectId) ?? false)) ||
				left.name.localeCompare(right.name, 'fr', { sensitivity: 'base' }) ||
				left.id - right.id
		);
}

function timetableAudiencesOverlap(
	left: TimetableEvent,
	right: TimetableEvent,
	groups: TimetableGroup[]
): boolean {
	const first = left.target_kind ?? 'promotion';
	const second = right.target_kind ?? 'promotion';
	if (first === 'promotion' || second === 'promotion') return true;
	if (first === second && first !== 'custom')
		return first === 'student'
			? left.target_user_id === right.target_user_id
			: left.target_number === right.target_number;
	const recipients = (event: TimetableEvent): number[] | undefined =>
		event.target_kind === 'student'
			? [event.target_user_id ?? 0]
			: groups.find(
					(group) =>
						group.promotion_id === event.promotion_id &&
						group.kind === event.target_kind &&
						group.number === event.target_number
				)?.student_ids;
	const firstIds = recipients(left);
	const secondIds = recipients(right);
	return firstIds && secondIds ? firstIds.some((id) => secondIds.includes(id)) : true;
}

/** Keep stable event references alongside each deduplicated conflict for warning navigation. */
export function timetableConflictDetails(
	events: TimetableEvent[],
	groups: TimetableGroup[] = [],
	today?: string
): TimetableWarning[] {
	const warnings = new Map<string, TimetableWarning>();
	let active: TimetableEvent[] = [];
	for (const event of [...events].sort(
		(left, right) => left.start.localeCompare(right.start) || left.id.localeCompare(right.id)
	)) {
		if (today && event.start.slice(0, 10) < today) continue;
		active = active.filter((other) => other.end.slice(0, 19) > event.start.slice(0, 19));
		const roomHalves = active.filter(
			(other) => other.room_id === event.room_id && other.target_kind === 'halves'
		).length;
		for (const other of active) {
			for (const [field, label] of [
				['teacher_id', 'enseignant'],
				['room_id', 'salle'],
				['promotion_id', 'classe']
			] as const) {
				if (field === 'promotion_id' && !timetableAudiencesOverlap(event, other, groups)) continue;
				if (
					field === 'room_id' &&
					event.target_kind === 'halves' &&
					other.target_kind === 'halves' &&
					roomHalves < 2
				)
					continue;
				const sameResource =
					field === 'promotion_id'
						? event.calendar_id === other.calendar_id ||
							(event.promotion_id !== null && event.promotion_id === other.promotion_id)
						: event[field] !== null && event[field] === other[field];
				if (sameResource) {
					const pair = [
						event.conflict_key ?? event.series_id,
						other.conflict_key ?? other.series_id
					].sort();
					const key = JSON.stringify([field, event[field] ?? event.calendar_id, pair]);
					if (!warnings.has(key))
						warnings.set(key, {
							code: `conflict-${key}`,
							severity: field === 'room_id' ? 'warning' : 'critical',
							message: `Conflit de ${label} le ${event.start.slice(0, 10)} : ${other.title} / ${event.title}.`,
							summary:
								field === 'promotion_id'
									? 'Les mêmes élèves ont plusieurs séances simultanées et ne peuvent pas être dans deux salles à la fois.'
									: `Conflit de ${label} entre ces séances.`,
							events: [other, event]
						});
				}
			}
		}
		active.push(event);
	}
	return [...warnings.values()].sort((a, b) => a.message.localeCompare(b.message)).slice(0, 100);
}

/** Compare actual dated segments with anonymous bookings in other calendars, once per recurring pair. */
export function crossCalendarTeacherConflicts(
	events: TimetableEvent[],
	commitments: TeacherCommitment[],
	today: string
): TimetableWarning[] {
	const bookings = new Map<string, TeacherCommitment[]>();
	for (const booking of commitments) {
		if (booking.start.slice(0, 10) < today) continue;
		const key = `${booking.teacher_id}:${booking.start.slice(0, 10)}`;
		const items = bookings.get(key) ?? [];
		items.push(booking);
		bookings.set(key, items);
	}
	const warnings = new Map<string, TimetableWarning>();
	for (const event of [...events].sort((a, b) => a.start.localeCompare(b.start))) {
		if (event.teacher_id === null || event.start.slice(0, 10) < today) continue;
		for (const booking of bookings.get(`${event.teacher_id}:${event.start.slice(0, 10)}`) ?? []) {
			if (
				event.calendar_id === booking.calendar_id ||
				event.start.slice(0, 19) >= booking.end.slice(0, 19) ||
				booking.start.slice(0, 19) >= event.end.slice(0, 19)
			)
				continue;
			const code = `teacher-busy-${JSON.stringify([event.calendar_id, event.conflict_key ?? event.series_id, event.teacher_id, booking.calendar_id, booking.conflict_key])}`;
			if (!warnings.has(code)) {
				const message = `${event.teacher || 'Cet enseignant'} est déjà occupé dans le calendrier ${booking.calendar_id} (${booking.calendar_label}).`;
				warnings.set(code, {
					code,
					severity: 'critical',
					message,
					summary: message,
					events: [event]
				});
			}
		}
	}
	return [...warnings.values()];
}

export interface AvailabilityRange {
	weekday: number;
	start: number;
	end: number;
}

/** Describe availability conflicts without losing the first affected occurrence's identity. */
export function teacherAvailabilityDetails(
	events: TimetableEvent[],
	patterns: NonNullable<TimetableBoard['availability']>,
	today?: string,
	schoolYear?: number
): TimetableWarning[] {
	const warnings = new Map<string, TimetableWarning>();
	for (const event of [...events].sort((a, b) => a.start.localeCompare(b.start))) {
		if (today && event.start.slice(0, 10) < today) continue;
		const pattern = patterns.find(
			(item) =>
				item.teacher_id === event.teacher_id &&
				item.school_year === (event.school_year ?? schoolYear)
		);
		if (event.teacher_id === null) continue;
		const weekday = (new Date(`${event.start.slice(0, 10)}T12:00:00Z`).getUTCDay() + 6) % 7;
		if (
			(
				pattern?.ranges ??
				Array.from({ length: 6 }, (_, weekday) => ({
					weekday,
					start: 28800,
					end: weekday === 5 ? 43200 : 68400
				}))
			).some(
				(range) =>
					range.weekday === weekday &&
					range.start <= clockSeconds(event.start.slice(11, 19)) &&
					clockSeconds(event.end.slice(11, 19)) <= range.end
			)
		)
			continue;
		const key = `${event.teacher_id}:${event.conflict_key ?? event.series_id}`;
		if (!warnings.has(key))
			warnings.set(key, {
				code: `availability-${key}`,
				message: `Disponibilité de ${event.teacher || 'l’enseignant'} : ${event.title} hors plage disponible${today ? ` le ${event.start.slice(0, 10)} (première occurrence concernée)` : ' dans la semaine type'}.`,
				summary: 'Cette séance est hors des plages de disponibilité de l’enseignant.',
				events: [event]
			});
	}
	return [...warnings.values()];
}

export function formatTeachingHours(hours: number): string {
	return `${hours.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} h`;
}

/** Snap a typed clock value to the closest available half-session, preserving seconds. */
export function nearestTimetableSlot(value: string, slots: [number, number][]): number {
	const seconds = clockSeconds(value);
	return slots.reduce(
		(best, slot, index) =>
			Math.abs(slot[0] - seconds) < Math.abs(slots[best][0] - seconds) ? index : best,
		0
	);
}

/** Resize either edge of a segmented session while preserving its untouched logical boundary. */
export function resizedTimetableSlots(
	event: Pick<TimetableEvent, 'start' | 'end' | 'start_slot' | 'duration_slots'>,
	start: number,
	end: number,
	slots: [number, number][]
): { start_slot: number; duration_slots: number } {
	if (!slots.length) throw new Error('Aucun créneau disponible.');
	const startChanged = start !== clockSeconds(event.start.slice(11, 19));
	const endChanged = end !== clockSeconds(event.end.slice(11, 19));
	const first = startChanged
		? nearestTimetableSlot(timetableClock(start), slots)
		: event.start_slot;
	let last = Math.min(slots.length - 1, event.start_slot + event.duration_slots - 1);
	if (endChanged) {
		last = first;
		for (let index = first; index < slots.length; index++)
			if (Math.abs(slots[index][1] - end) < Math.abs(slots[last][1] - end)) last = index;
	}
	const boundedFirst = Math.min(first, last);
	return { start_slot: boundedFirst, duration_slots: last - boundedFirst + 1 };
}

/** Preserve half-session seconds instead of rounding to the nearest minute. */
export function timetableClock(seconds: number): string {
	return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
		.map((part) => String(part).padStart(2, '0'))
		.join(':');
}
export function clockSeconds(value: string): number {
	const [hour = 0, minute = 0, second = 0] = value.split(':').map(Number);
	return hour * 3600 + minute * 60 + second;
}
/** Return holiday names on inclusive dates within the calendar's school year. */
export function timetableHolidayLabel(settings: TimetableSettings, day: string): string | null {
	if (day < settings.start || day > settings.end) return null;
	const names = settings.holidays
		.filter((holiday) => holiday.start <= day && day <= holiday.end)
		.map((holiday) => holiday.name);
	return names.length ? `Vacances · ${names.join(' · ')}` : null;
}

interface TimetableBackground {
	id: string;
	title: string;
	start: string;
	end: string;
	display: 'background';
	backgroundColor: string;
	classNames: string[];
	editable: false;
}

/** Paint holidays instead of recess and lunch, without creating timetable sessions. */
export function timetableBackgrounds(
	settings: TimetableSettings,
	date: string,
	{ dateless = false, showLunch = true }: { dateless?: boolean; showLunch?: boolean } = {}
): TimetableBackground[] {
	return Array.from({ length: settings.saturday ? 6 : 5 }, (_, index) =>
		shiftTimetableDate(mondayOf(date), index)
	).flatMap((day): TimetableBackground[] => {
		const holiday = dateless ? null : timetableHolidayLabel(settings, day);
		if (holiday) {
			return [
				{
					id: `holiday-${day}`,
					title: holiday,
					start: `${day}T${timetableClock(Math.floor(settings.day_start / 3600) * 3600)}`,
					end: `${day}T${timetableClock(Math.ceil(settings.day_end / 3600) * 3600)}`,
					display: 'background',
					backgroundColor: 'var(--color-danger-soft)',
					classNames: ['timetable-holiday'],
					editable: false
				}
			];
		}
		const backgrounds: TimetableBackground[] = settings.breaks.map((pause, index) => ({
			id: `pause-${day}-${index}`,
			title: 'Pause',
			start: `${day}T${timetableClock(pause.start)}`,
			end: `${day}T${timetableClock(pause.end)}`,
			display: 'background',
			backgroundColor: 'var(--color-border)',
			classNames: [],
			editable: false
		}));
		if (showLunch && !dateless)
			backgrounds.push({
				id: `self-${day}`,
				title: 'Self ouvert · cours autorisés',
				start: `${day}T${timetableClock(settings.lunch_start ?? 43200)}`,
				end: `${day}T${timetableClock(settings.lunch_end ?? 50400)}`,
				display: 'background',
				backgroundColor: 'var(--color-success-soft)',
				classNames: ['timetable-lunch'],
				editable: false
			});
		return backgrounds;
	});
}

export function defaultTimetableSettings(year: number): TimetableSettings {
	return {
		start: `${year}-09-01`,
		end: `${year + 1}-06-30`,
		day_start: 28800,
		day_end: 68100,
		session_minutes: 55,
		lunch_start: 43200,
		lunch_end: 50400,
		saturday: false,
		breaks: [
			{ start: 35400, end: 36600 },
			{ start: 57000, end: 58200 }
		],
		holidays: []
	};
}

/** Count complete nominal sessions outside recess and the self window, merging overlaps once. */
export function timetableDayBalance(
	settings: TimetableSettings
): { sessions: number; remainingSeconds: number; teachingSeconds: number } | null {
	const span = settings.day_end - settings.day_start;
	const session = settings.session_minutes * 60;
	if (!Number.isFinite(span) || !Number.isFinite(session) || span <= 0 || session <= 0) return null;
	const intervals = [
		...settings.breaks,
		{ start: settings.lunch_start ?? 43200, end: settings.lunch_end ?? 50400 }
	]
		.map((interval) => [
			Math.max(settings.day_start, interval.start),
			Math.min(settings.day_end, interval.end)
		])
		.filter(([start, end]) => start < end)
		.sort((a, b) => a[0] - b[0]);
	let excluded = 0,
		cursor = settings.day_start;
	for (const [start, end] of intervals) {
		excluded += Math.max(0, end - Math.max(cursor, start));
		cursor = Math.max(cursor, end);
	}
	const teachingSeconds = span - excluded;
	return {
		sessions: Math.floor(teachingSeconds / session),
		remainingSeconds: teachingSeconds % session,
		teachingSeconds
	};
}

/** Keep the civil date stable across UTC offsets and daylight-saving boundaries. */
export function shiftTimetableDate(value: string, days: number): string {
	const date = new Date(`${value}T12:00:00Z`);
	date.setUTCDate(date.getUTCDate() + days);
	return date.toISOString().slice(0, 10);
}
export function mondayOf(value: string): string {
	const weekday = new Date(`${value}T12:00:00Z`).getUTCDay();
	return shiftTimetableDate(value, -(weekday + 6) % 7);
}
export function isoWeek(value: string): number {
	const date = new Date(`${value}T12:00:00Z`);
	date.setUTCDate(date.getUTCDate() + 3 - ((date.getUTCDay() + 6) % 7));
	const first = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
	return (
		1 +
		Math.round(
			((date.getTime() - first.getTime()) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7
		)
	);
}
