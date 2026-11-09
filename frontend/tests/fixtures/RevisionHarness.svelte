<script lang="ts">
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	import KholloscopeRevision from '../../src/lib/components/KholloscopeRevision.svelte';
	import type { RevisionView } from '../../src/lib/kholloscopeRevision';
	import type { TimetableCatalog } from '../../src/lib/timetable';
	const initial: RevisionView = {
		rooms: [
			{ id: 1, name: 'Salle A', kholle_capacity: 1 },
			{ id: 2, name: 'Salle B', kholle_capacity: 2 },
			{ id: 3, name: 'Salle fermée aux khôlles', kholle_capacity: 0 }
		],
		needs_recalculation: true,
		problems: [
			{
				kind: 'groups',
				calendar_id: 1,
				message:
					'PT : kholloscope créé pour 15 groupes ; 14 groupes détectés actuellement. Une révision et un recalcul sont nécessaires.'
			}
		],
		published_sessions: [],
		calendars: [
			{
				id: 1,
				calendar_id: 1,
				school_year: 2026,
				revision: null,
				slots: [],
				weeks: {},
				series: [],
				settings: {
					start: '2026-09-01',
					end: '2027-07-01',
					session_minutes: 55,
					day_start: 28800,
					day_end: 61200,
					lunch_start: 43200,
					lunch_end: 50400,
					breaks: [],
					holidays: [],
					saturday: false
				}
			}
		],
		source_revision: 'a'.repeat(64),
		next_monday: '2026-11-09',
		branch: null,
		subjects: [
			{
				id: 1,
				name: 'Mathématiques',
				color: '#123456',
				icon: 'book',
				cycle_weeks: 2,
				required_service: 2,
				staff: [
					{
						id: 1,
						name: 'Ancien khôlleur',
						first_name: 'Ancien',
						last_name: 'Khôlleur',
						roles: ['kholleur'],
						sessions: 2
					},
					{
						id: 2,
						name: 'Nouveau khôlleur',
						first_name: 'Nouveau',
						last_name: 'Khôlleur',
						roles: ['kholleur'],
						sessions: 0
					}
				]
			}
		]
	};
	if (new URL(window.location.href).searchParams.has('multi')) {
		initial.subjects.push({
			...initial.subjects[0],
			id: 2,
			name: 'Physique',
			color: '#734560',
			staff: [{ ...initial.subjects[0].staff[0], sessions: 2 }]
		});
	}
	const catalog: TimetableCatalog = {
		administrator: true,
		today: '2026-11-08',
		calendars: [],
		promotions: [],
		teachers: [
			{ id: 1, name: 'Ancien khôlleur' },
			{ id: 2, name: 'Nouveau khôlleur' }
		],
		subjects: [{ id: 1, name: 'Mathématiques', color: '#123456' }],
		rooms: [
			{ id: 1, name: 'Salle A' },
			{ id: 2, name: 'Salle B' }
		]
	};
</script>

<main class="p-4"><KholloscopeRevision {initial} {catalog} year={2026} canWrite={true} /></main>
