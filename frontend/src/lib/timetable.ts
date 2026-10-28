/** Audience-scoped timetable contracts; persisted times are seconds after midnight. */
export interface TimetableSettings {
	start: string;
	end: string;
	day_start: number;
	day_end: number;
	session_minutes: number;
	saturday: boolean;
	breaks: { start: number; end: number }[];
	holidays: { name: string; start: string; end: string }[];
}
export interface TimetableBlock {
	starts_on: string;
	start_slot: number;
	duration_slots: number;
	subject_id: number | null;
	teacher_id: number | null;
	room_id: number | null;
	kind: 'course' | 'td' | 'tp' | 'kholle';
	title: string;
	interval: 0 | 1 | 2 | 3;
	until: string | null;
	target_kind?: 'promotion' | 'halves' | 'thirds' | 'kholles' | 'student';
	target_number?: number | null;
	target_user_id?: number | null;
}
export interface TimetableSeries extends TimetableBlock {
	id: string;
	lineage: string;
	template_key?: string | null;
	exceptions: Record<string, Omit<TimetableBlock, 'interval' | 'until'> | null>;
}
export interface TimetableEvent {
	id: string;
	series_id: string;
	conflict_key?: string;
	template_key?: string | null;
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
	published_revision: string | null;
	slots: [number, number][];
	weeks: Record<string, number>;
	series: TimetableSeries[];
	template_blocks?: WeeklyBlock[];
}
export interface TimetableAgenda {
	id: number;
	name: string;
	promotion_id: number | null;
	revision: string | null;
	is_paused?: boolean;
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
	calendars?: Pick<TimetableAgenda, 'id' | 'name' | 'promotion_id' | 'revision' | 'is_paused'>[];
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
	severity: 'warning' | 'critical';
	message: string;
	teacher_id?: number;
	template_keys?: string[];
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
	settings: TimetableSettings | null;
	revision: string;
	alternatives: { name: string; settings: TimetableSettings }[];
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
	kind: 'halves' | 'thirds' | 'kholles';
	number: number;
	student_ids: number[];
}
export interface WeeklyBlock extends Omit<TimetableBlock, 'starts_on' | 'until' | 'interval'> {
	key: string;
	weekday: number;
	interval: 1 | 2 | 3;
	phase: number;
}
export interface WeeklyTemplate {
	revision: string;
	blocks: WeeklyBlock[];
	versions: { number: number; effective_on: string; effective_at?: string }[];
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
	const partitions = groups.filter((group) => group.promotion_id === promotionId);
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
	for (const kind of ['halves', 'thirds', 'kholles']) {
		for (const group of partitions
			.filter((item) => item.kind === kind)
			.sort((a, b) => a.number - b.number)) {
			const label =
				kind === 'kholles'
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
	if (!priority) root.children = remaining.map(pupilNode);
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

/** Render a weekly scratch block using the same effective teaching seconds as the backend. */
export function weeklyEvents(
	blocks: WeeklyBlock[],
	year: TimetableYear,
	monday: string,
	promotionId: number | null
): TimetableEvent[] {
	return blocks.flatMap((block) => {
		const start = year.slots[block.start_slot]?.[0];
		const end = year.slots[block.start_slot + block.duration_slots - 1]?.[1];
		if (start === undefined || end === undefined) return [];
		const day = shiftTimetableDate(monday, block.weekday);
		const pieces: [number, number][] = [];
		let cursor = start;
		for (const pause of [...year.settings.breaks].sort((a, b) => a.start - b.start)) {
			if (pause.end <= cursor || pause.start >= end) continue;
			if (cursor < pause.start) pieces.push([cursor, pause.start]);
			cursor = pause.end;
		}
		if (cursor < end) pieces.push([cursor, end]);
		return pieces.map(([from, to], index) => ({
			...block,
			id: `${block.key}-${index}`,
			series_id: block.key,
			source_date: day,
			start: `${day}T${timetableClock(from)}`,
			end: `${day}T${timetableClock(to)}`,
			calendar_id: year.calendar_id,
			year_id: year.id,
			promotion_id: promotionId,
			color: '#244BC1',
			teacher: '',
			room: ''
		}));
	});
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
		default:
			return 'Classe entière';
	}
}

/** Compare complete patterns independently of ordering and omitted audience defaults. */
export function weeklySignature(blocks: WeeklyBlock[]): string {
	return JSON.stringify(
		[...blocks]
			.sort((a, b) => a.key.localeCompare(b.key))
			.map((block) => [
				block.key,
				block.weekday,
				block.start_slot,
				block.duration_slots,
				block.subject_id,
				block.teacher_id,
				block.room_id,
				block.kind,
				block.title,
				block.interval,
				block.phase,
				block.target_kind ?? 'promotion',
				block.target_number ?? null,
				block.target_user_id ?? null
			])
	);
}

/** Treat 55–65 minute teaching sessions as one pedagogical hour, including half-sessions. */
export function teachingHours(durationSlots: number, sessionMinutes: number): number {
	return (
		(durationSlots / 2) * (sessionMinutes >= 55 && sessionMinutes <= 65 ? 1 : sessionMinutes / 60)
	);
}

export interface SubjectHours {
	subjectId: number | null;
	course: number;
	td: number;
	tp: number;
}

/** Average a full recurrence cycle from a pupil's perspective; khôlles never contribute. */
export function weeklySubjectHours(blocks: WeeklyBlock[], sessionMinutes: number): SubjectHours[] {
	const totals = new Map<number | null, SubjectHours>();
	for (const block of blocks) {
		if (
			block.kind === 'kholle' ||
			!['promotion', 'halves', 'thirds'].includes(block.target_kind ?? 'promotion')
		)
			continue;
		const value = totals.get(block.subject_id) ?? {
			subjectId: block.subject_id,
			course: 0,
			td: 0,
			tp: 0
		};
		const size = block.target_kind === 'halves' ? 2 : block.target_kind === 'thirds' ? 3 : 1;
		value[block.kind] +=
			teachingHours(block.duration_slots, sessionMinutes) / block.interval / size;
		totals.set(block.subject_id, value);
	}
	const total = (row: SubjectHours): number => row.course + row.td + row.tp;
	return [...totals.values()].sort(
		(left, right) => total(right) - total(left) || (left.subjectId ?? 0) - (right.subjectId ?? 0)
	);
}

/** Report unequal teaching loads and missing promotion groups without blocking draft saves. */
export function weeklyIssues(
	blocks: WeeklyBlock[],
	sessionMinutes: number,
	promotionId: number | null,
	groups: TimetableGroup[],
	subjects: { id: number; name: string }[]
): TimetableIssue[] {
	const issues: TimetableIssue[] = [];
	const loads = new Map<
		string,
		{ kind: 'halves' | 'thirds'; subject: number | null; hours: number[] }
	>();
	const missing = new Set<string>();
	for (const block of blocks) {
		if (
			block.kind === 'kholle' ||
			(block.target_kind !== 'halves' && block.target_kind !== 'thirds')
		)
			continue;
		const size = block.target_kind === 'halves' ? 2 : 3;
		const number = block.target_number ?? 0;
		if (number < 1 || number > size) continue;
		const key = `${block.target_kind}-${block.subject_id}`;
		const load = loads.get(key) ?? {
			kind: block.target_kind,
			subject: block.subject_id,
			hours: Array.from({ length: size }, () => 0)
		};
		load.hours[number - 1] += teachingHours(block.duration_slots, sessionMinutes) / block.interval;
		loads.set(key, load);
		if (
			promotionId !== null &&
			!groups.some(
				(group) =>
					group.promotion_id === promotionId &&
					group.kind === block.target_kind &&
					group.number === number &&
					group.student_ids.length
			)
		) {
			missing.add(`${block.target_kind}-${number}`);
		}
	}
	for (const [key, load] of loads) {
		if (Math.max(...load.hours) - Math.min(...load.hours) < 1e-8) continue;
		const detail = load.hours
			.map(
				(hours, index) =>
					`${String.fromCharCode((load.kind === 'halves' ? 65 : 88) + index)} : ${formatTeachingHours(hours)}`
			)
			.join(' · ');
		issues.push({
			code: `balance-${key}`,
			severity: 'warning',
			message: `${subjects.find((subject) => subject.id === load.subject)?.name ?? 'Sans matière'} : volumes inégaux entre groupes (${detail}), cours, TD et TP confondus. Comparez les élèves sur le cycle complet.`,
			template_keys: blocks
				.filter(
					(block) =>
						block.target_kind === load.kind &&
						block.subject_id === load.subject &&
						block.kind !== 'kholle'
				)
				.map((block) => block.key)
		});
	}
	for (const key of missing) {
		const [kind, number] = key.split('-');
		const label = String.fromCharCode((kind === 'halves' ? 64 : 87) + Number(number));
		issues.push({
			code: `group-${key}`,
			severity: 'warning',
			message: `Le groupe ${label} utilisé dans la semaine type n’est pas défini ou ne contient aucun élève dans la promotion affectée.`,
			template_keys: blocks
				.filter((block) => block.target_kind === kind && block.target_number === Number(number))
				.map((block) => block.key)
		});
	}
	return issues;
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
	if (first === second)
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

/** Preview current conflicts; a room can accommodate two simultaneous half-class sessions. */
export function timetableConflicts(
	events: TimetableEvent[],
	groups: TimetableGroup[] = [],
	today?: string
): string[] {
	return timetableConflictDetails(events, groups, today).map((warning) => warning.message);
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

/** Project a dated creation/replacement with its own recurrence anchor, excluding holidays and pauses. */
export function datedBlockEvents(
	block: TimetableBlock,
	year: TimetableYear,
	promotionId: number | null,
	key: string
): TimetableEvent[] {
	const weekday = (new Date(`${block.starts_on}T12:00:00Z`).getUTCDay() + 6) % 7;
	const anchor = year.weeks[mondayOf(block.starts_on)];
	const pattern: WeeklyBlock = {
		...block,
		key,
		weekday,
		interval: Math.max(1, block.interval) as 1 | 2 | 3,
		phase: 1
	};
	const segments = weeklyEvents([pattern], year, mondayOf(block.starts_on), promotionId);
	const dates = !block.interval
		? [block.starts_on]
		: Object.entries(year.weeks)
				.filter(([, number]) => anchor !== undefined && (number - anchor) % block.interval === 0)
				.map(([monday]) => shiftTimetableDate(monday, weekday));
	return dates
		.filter(
			(day) =>
				day >= block.starts_on &&
				day >= year.settings.start &&
				day <= (block.interval ? (block.until ?? year.settings.end) : year.settings.end) &&
				day <= year.settings.end &&
				(weekday !== 5 || year.settings.saturday) &&
				weekday !== 6 &&
				!year.settings.holidays.some((holiday) => holiday.start <= day && day <= holiday.end)
		)
		.flatMap((day) =>
			segments.map((event) => ({
				...event,
				id: `${event.id}-${day}`,
				source_date: day,
				start: `${day}T${event.start.slice(11, 19)}`,
				end: `${day}T${event.end.slice(11, 19)}`
			}))
		);
}

export interface AvailabilityRange {
	weekday: number;
	start: number;
	end: number;
}

/** Check actual teaching segments, once per recurring teacher assignment. */
export function teacherAvailabilityWarnings(
	events: TimetableEvent[],
	patterns: NonNullable<TimetableBoard['availability']>,
	today?: string,
	schoolYear?: number
): string[] {
	return teacherAvailabilityDetails(events, patterns, today, schoolYear).map(
		(warning) => warning.message
	);
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
		if (!pattern) continue;
		const weekday = (new Date(`${event.start.slice(0, 10)}T12:00:00Z`).getUTCDay() + 6) % 7;
		if (
			pattern.ranges.some(
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

/** Check every phase of the two/three-week cycles while a template is being edited. */
export function weeklyConflicts(
	events: TimetableEvent[],
	blocks: WeeklyBlock[],
	groups: TimetableGroup[]
): string[] {
	const patterns = new Map(blocks.map((block) => [block.key, block]));
	const warnings = new Set<string>();
	for (let week = 1; week <= 6; week++) {
		const active = events.filter((event) => {
			const block = patterns.get(event.series_id);
			return block && ((week - 1) % block.interval) + 1 === block.phase;
		});
		for (const warning of timetableConflicts(active, groups)) warnings.add(warning);
	}
	return [...warnings].sort().slice(0, 100);
}

/** Project an unsaved pattern only onto remaining open dates and actual recurrence phases. */
export function futureTemplateEvents(
	events: TimetableEvent[],
	blocks: WeeklyBlock[],
	year: TimetableYear,
	today: string
): TimetableEvent[] {
	const patterns = new Map(blocks.map((block) => [block.key, block]));
	return Object.entries(year.weeks).flatMap(([monday, number]) => {
		if (shiftTimetableDate(monday, 6) < today) return [];
		return events.flatMap((event) => {
			const block = patterns.get(event.series_id);
			if (!block || ((number - 1) % block.interval) + 1 !== block.phase) return [];
			const day = shiftTimetableDate(monday, block.weekday);
			if (
				day < today ||
				day < year.settings.start ||
				day > year.settings.end ||
				(block.weekday === 5 && !year.settings.saturday) ||
				year.settings.holidays.some((holiday) => holiday.start <= day && day <= holiday.end)
			)
				return [];
			return [
				{
					...event,
					id: `${event.id}-${day}`,
					source_date: day,
					start: `${day}T${event.start.slice(11, 19)}`,
					end: `${day}T${event.end.slice(11, 19)}`
				}
			];
		});
	});
}

/** Compare a weekly draft with retained independent lessons and actual occurrence exceptions. */
export function previewTemplateEvents(
	events: TimetableEvent[],
	blocks: WeeklyBlock[],
	year: TimetableYear,
	today: string,
	dated: TimetableEvent[]
): TimetableEvent[] {
	const sources = new Map(year.series.map((source) => [source.id, source]));
	const keys = new Set(blocks.map((block) => block.key));
	const weeklySource = (source: TimetableSeries): boolean =>
		source.interval > 0 &&
		source.kind !== 'kholle' &&
		['promotion', 'halves', 'thirds'].includes(source.target_kind ?? 'promotion');
	const sourceKey = (event: TimetableEvent): string | null => {
		const source = sources.get(event.series_id);
		if (source && !weeklySource(source)) return null;
		return (
			event.template_key ??
			source?.template_key ??
			(source?.interval && source.kind !== 'kholle' && keys.has(source.lineage)
				? source.lineage
				: null)
		);
	};
	const exceptions = new Set<string>();
	for (const source of year.series) {
		if (!weeklySource(source)) continue;
		const key = source.template_key ?? (keys.has(source.lineage) ? source.lineage : null);
		if (key) for (const day of Object.keys(source.exceptions)) exceptions.add(`${key}:${day}`);
	}
	for (const event of dated)
		if (event.is_exception && sourceKey(event))
			exceptions.add(`${sourceKey(event)}:${event.source_date}`);
	const projected = futureTemplateEvents(events, blocks, year, today).filter(
		(event) => !exceptions.has(`${event.series_id}:${event.source_date}`)
	);
	const independent = dated.filter(
		(event) =>
			!sourceKey(event) ||
			event.is_exception ||
			Object.hasOwn(sources.get(event.series_id)?.exceptions ?? {}, event.source_date)
	);
	return [...projected, ...independent];
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
export function defaultTimetableSettings(year: number): TimetableSettings {
	return {
		start: `${year}-09-01`,
		end: `${year + 1}-06-30`,
		day_start: 28800,
		day_end: 61200,
		session_minutes: 55,
		saturday: false,
		breaks: [
			{ start: 35400, end: 36600 },
			{ start: 43200, end: 46800 },
			{ start: 53400, end: 54600 }
		],
		holidays: []
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
