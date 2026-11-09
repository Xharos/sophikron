import { requirePageAccess } from '#lib/server/forms';
import { hasPermission } from '#lib/access';
import { api } from '#lib/server/api';
import { BackendError } from '#lib/server/backend';
import { error } from '@sveltejs/kit';
import type { KholleSettings } from '#lib/kholle';
import type { Subject } from '#lib/site';
import type { TimetableCatalog } from '#lib/timetable';
import type { GenerationView } from '#lib/kholloscopeGeneration';
import type { RevisionView } from '#lib/kholloscopeRevision';
import {
	kholloscopeStepStates,
	type KholleWishes,
	type KholloscopeWorkflow,
	type KholloscopeStep
} from '#lib/kholleWishes';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async (event) => {
	requirePageAccess(event, 'kholloscope');
	try {
		const year = event.url.searchParams.get('school_year');
		const tab = event.url.searchParams.get('tab') ?? 'volumes';
		if (!['volumes', 'wishes', 'service', 'generation', 'groups', 'revision'].includes(tab))
			error(422, 'Étape inconnue.');
		if (year !== null && !/^\d{4}$/.test(year)) error(422, 'Année scolaire invalide.');
		const overview = await api<{
			years: number[];
			school_year: number | null;
			errors: string[];
			calendars: {
				id: number;
				name: string;
				weeks: number;
				group_count: number;
				group_size: number | null;
				settings: Omit<KholleSettings, 'subjects'> & {
					subjects: (KholleSettings['subjects'][number] &
						Pick<Subject, 'name' | 'icon' | 'color'>)[];
				};
			}[];
		}>(event, '/timetable/kholloscope' + (year ? `?school_year=${year}` : ''));
		const workflow =
			overview.school_year === null
				? null
				: await api<KholloscopeWorkflow>(
						event,
						`/timetable/kholloscope/${overview.school_year}/workflow`
					);
		const generation =
			overview.school_year !== null
				? await api<GenerationView>(
						event,
						`/timetable/kholloscope/${overview.school_year}/generation`
					)
				: null;
		const accessible =
			kholloscopeStepStates(workflow, generation, tab as KholloscopeStep).find(
				(step) => step.id === tab
			)?.available ?? false;
		const accessError = !accessible
			? 'Cette étape est verrouillée. Choisissez une année préparée et validez l’étape précédente.'
			: null;
		return {
			revision:
				tab === 'revision' && accessible && overview.school_year !== null
					? await api<RevisionView>(
							event,
							`/timetable/kholloscope/${overview.school_year}/revision`
						)
					: null,
			canWrite: hasPermission(event.locals.user, 'kholloscope.write'),
			generation,
			catalog: await api<TimetableCatalog>(event, '/timetable/catalog'),
			tab: tab as KholloscopeStep,
			workflow,
			accessError,
			overview,
			wishes:
				overview.school_year === null
					? null
					: await api<KholleWishes>(event, `/timetable/kholloscope/${overview.school_year}/wishes`)
		};
	} catch (cause) {
		if (cause instanceof BackendError) error(cause.status, cause.message);
		throw cause;
	}
};
