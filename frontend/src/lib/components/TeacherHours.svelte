<script lang="ts">
	import StatisticChart from './statistics/StatisticChart.svelte';
	import { blockKinds, formatTeachingHours, type TimetableEvent } from '#lib/timetable';
	import { teacherSubjectHours } from '#lib/teacherTimetable';
	let {
		events,
		sessionMinutes,
		subjects
	}: {
		events: TimetableEvent[];
		sessionMinutes: number;
		subjects: { id: number; name: string }[];
	} = $props();
	const totals = $derived(teacherSubjectHours(events, sessionMinutes));
	const series = $derived(
		(['course', 'td', 'tp', 'kholle'] as const).map((kind, index) => ({
			key: kind,
			label: blockKinds[kind],
			color: ['#244BC1', '#2E8B57', '#A34E18', '#9747BB'][index],
			values: totals.map((row) => row[kind])
		}))
	);
</script>

<p class="muted mb-4">
	Heures affectées pendant la semaine consultée, par matière et par volume décroissant. Les pauses
	sont exclues. Une séance de 55 à 65 minutes compte pour une heure, sans pondération par groupe
	d’élèves. En sélection multiple, les heures des enseignants s’additionnent.
</p>
{#if totals.length}
	<StatisticChart
		title="Heures des enseignants par matière"
		kind="stacked"
		{series}
		labels={totals.map(
			(row) => subjects.find((subject) => subject.id === row.subjectId)?.name ?? 'Sans matière'
		)}
		format={formatTeachingHours}
	/>
{:else}<p role="status">Aucune séance affectée pendant cette semaine.</p>{/if}
