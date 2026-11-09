import type { Subject } from './site';
import type { GenerationView } from './kholloscopeGeneration';

export type PreparationStep = 'volumes' | 'wishes' | 'service';
export type KholloscopeStep = PreparationStep | 'generation' | 'groups' | 'revision';

export const kholloscopeSteps: { id: KholloscopeStep; label: string }[] = [
	{ id: 'volumes', label: 'Calendriers et volumes' },
	{ id: 'wishes', label: 'Souhaits de service' },
	{ id: 'service', label: 'Service et salles' },
	{ id: 'generation', label: 'Génération du calendrier' },
	{ id: 'groups', label: 'Affectation des groupes' },
	{ id: 'revision', label: 'Révision' }
];

/** Derive navigation and color from the same strict chain of current saved confirmations. */
export function kholloscopeStepStates(
	workflow: KholloscopeWorkflow | null,
	generation: GenerationView | null,
	current: KholloscopeStep,
	dirtyStep: KholloscopeStep | null = null
): {
	id: KholloscopeStep;
	label: string;
	available: boolean;
	validated: boolean;
	current: boolean;
	review: boolean;
	pending: boolean;
}[] {
	const run = generation?.run;
	const published = !!run?.result?.applied;
	const management = !!(run?.result?.applied || run?.result?.withdrawn);
	const complete = run?.status === 'completed' && !!run.result;
	const confirmedGeneration =
		complete && !!(run.result?.saved || run.result?.mappings.length || management);
	const saved: Record<KholloscopeStep, boolean> = {
		volumes: !!workflow?.validated.volumes && !workflow.errors.length,
		wishes: !!workflow?.validated.wishes && !workflow.wish_errors.length,
		service: !!workflow?.validated.service,
		generation: confirmedGeneration && (!run?.stale || !!run?.result?.applied),
		groups:
			complete &&
			!!run.result?.mappings.length &&
			(!run.stale || !!run.result?.applied) &&
			!run.result?.withdrawn,
		revision: false
	};
	let previousValid = true;
	let invalidated = false;
	return kholloscopeSteps.map((step) => {
		if (step.id === 'revision') {
			const attention = !!(
				generation?.revision_state?.conflicts || generation?.revision_state?.pending
			);
			return {
				...step,
				available: published,
				validated: published && !attention,
				current: current === 'revision',
				review: false,
				pending: published && attention
			};
		}
		if (published) {
			return {
				...step,
				available: true,
				validated: true,
				current: step.id === current,
				review: false,
				pending: false
			};
		}
		const confirmed =
			step.id === 'generation'
				? confirmedGeneration
				: step.id === 'groups'
					? complete && !!run.result?.mappings.length
					: !!workflow?.validated[step.id] || !!workflow?.review[step.id];
		const needsReview =
			step.id === 'generation' || step.id === 'groups'
				? confirmed && !!run?.stale && !run.result?.applied
				: !!workflow?.review[step.id];
		invalidated ||= needsReview || dirtyStep === step.id;
		// Dependencies are invalidated for navigation, but untouched steps are not reconfirmations.
		const review = invalidated && confirmed;
		const available =
			previousValid || ((step.id === 'groups' || step.id === 'wishes') && management);
		const validated = previousValid && saved[step.id] && !invalidated;
		const state = {
			...step,
			available,
			validated,
			current: step.id === current,
			review,
			pending: !validated && previousValid
		};
		previousValid = validated;
		return state;
	});
}

/** Describe a preference for one or several assigned promotions. */
export function promotionPreferenceText(count: number, indifferent = false): string {
	return indifferent
		? 'Indifférent'
		: count > 1
			? 'Ses promotions en priorité'
			: 'Sa promotion en priorité';
}
export interface KholloscopeWorkflow {
	school_year: number;
	revision: string;
	errors: string[];
	wish_errors: string[];
	validated: Record<PreparationStep, boolean>;
	available: Record<PreparationStep, boolean>;
	review: Record<PreparationStep, boolean>;
	conflicts: Record<PreparationStep, string[]>;
	needs: Record<number, number>;
	subjects: KholleWishes['subjects'];
	rooms: { id: number; name: string; revision: string; kholle_capacity: number }[];
	selected_rooms: { subject_id: number; room_ids: number[] }[];
	teacher_preferences: {
		user_id: number;
		prefer_own_promotion: boolean;
		effective: boolean;
		promotion_ids: number[];
	}[];
}

/** Compare room sets independently of selection order and empty, unselected entries. */
export function roomSelectionKey(selection: Record<number, number[]>): string {
	return JSON.stringify(
		Object.entries(selection)
			.filter(([, rooms]) => rooms.length)
			.map(
				([subject, rooms]) => [Number(subject), [...new Set(rooms)].sort((a, b) => a - b)] as const
			)
			.sort((left, right) => left[0] - right[0])
	);
}

export interface KholleWishPerson {
	id: number;
	name: string;
	first_name: string;
	last_name: string;
	roles: ('teacher' | 'kholleur')[];
	sessions: number | null;
	sessions_a?: number | null;
	sessions_b?: number | null;
}

export interface KholleWishes {
	school_year: number;
	revision: string;
	subjects: (Pick<Subject, 'id' | 'name' | 'color' | 'icon'> & {
		cycle_weeks?: number;
		previous_cycle_weeks?: number;
		staff: KholleWishPerson[];
	})[];
	unassigned: Omit<KholleWishPerson, 'sessions'>[];
}

export interface KholleWishEntry {
	user_id: number;
	subject_id: number;
	sessions: number | null;
}

/** Teachers (including dual roles) precede khôlleurs, then sort by French family/given name. */
export function compareWishPeople(
	left: Pick<KholleWishPerson, 'id' | 'roles' | 'first_name' | 'last_name'>,
	right: Pick<KholleWishPerson, 'id' | 'roles' | 'first_name' | 'last_name'>
): number {
	return (
		Number(right.roles.includes('teacher')) - Number(left.roles.includes('teacher')) ||
		left.last_name.localeCompare(right.last_name, 'fr', { sensitivity: 'base' }) ||
		left.first_name.localeCompare(right.first_name, 'fr', { sensitivity: 'base' }) ||
		left.id - right.id
	);
}

/** Show only subjects with a strictly positive allocated annual weekly volume. */
export function allocatedWishSubjects(
	subjects: KholleWishes['subjects'],
	needs: Record<number, number> | null
): KholleWishes['subjects'] {
	return subjects.filter((subject) => (needs?.[subject.id] ?? 0) > 0);
}

/** Preserve saved wishes for hidden subjects when submitting the complete API roster. */
export function completeWishEntries(
	subjects: KholleWishes['subjects'],
	edited: KholleWishEntry[]
): KholleWishEntry[] {
	const values = new Map(edited.map((entry) => [`${entry.subject_id}-${entry.user_id}`, entry]));
	return subjects.flatMap((subject) =>
		subject.staff.map(
			(person) =>
				values.get(`${subject.id}-${person.id}`) ?? {
					user_id: person.id,
					subject_id: subject.id,
					sessions: person.sessions
				}
		)
	);
}

/** Empty is unfilled; zero is an explicit commitment to no sessions. */
export function wishSessions(value: string): number | null | undefined {
	if (!value.trim()) return null;
	if (!/^\d+$/.test(value.trim())) return undefined;
	const sessions = Number(value);
	return Number.isSafeInteger(sessions) && sessions <= 1000 ? sessions : undefined;
}

/** Missing entries take precedence over a numerical balance, including an empty roster. */
export function wishBalance(
	values: (number | null)[],
	weeklyNeed: number | null,
	cycleWeeks = 2
): { total: number; missing: number; difference: number | null; label: string } {
	const total = values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
	const missing = values.filter((value) => value === null).length;
	const difference = weeklyNeed === null ? null : total / cycleWeeks - weeklyNeed;
	const label =
		missing || !values.length
			? 'Souhaits incomplets'
			: difference === null
				? 'Besoin non disponible'
				: Math.abs(difference) < 1e-7
					? 'Volumes équilibrés'
					: difference < 0
						? 'Volume insuffisant'
						: 'Volume excédentaire';
	return { total, missing, difference, label };
}
