<script lang="ts">
	import StatisticChart from './statistics/StatisticChart.svelte';
	import { blockKinds, formatTeachingHours, type AnnualSubjectHours } from '#lib/timetable';
	let {
		hours,
		weeks,
		subjects
	}: {
		hours: AnnualSubjectHours[];
		weeks: number;
		subjects: { id: number; name: string }[];
	} = $props();
	let average = $state(true);
	const totals = $derived(
		hours.map((row) => ({ subjectId: row.subject_id, ...(average ? row.weekly : row) }))
	);
	const names = $derived(
		totals.map(
			(row) => subjects.find((subject) => subject.id === row.subjectId)?.name ?? 'Sans matière'
		)
	);
	const series = $derived(
		(['course', 'td', 'tp', 'kholle'] as const).map((kind, index) => ({
			key: kind,
			label: blockKinds[kind],
			color: ['#244BC1', '#2E8B57', '#A34E18', '#9747BB'][index],
			values: totals.map((row) => row[kind])
		}))
	);
</script>

<div class="buttons mb-4">
	<button
		class="button"
		class:is-primary={average}
		aria-pressed={average}
		onclick={() => (average = true)}>Moyenne par semaine</button
	>
	<button
		class="button"
		class:is-primary={!average}
		aria-pressed={!average}
		onclick={() => (average = false)}>Total sur l’année</button
	>
</div>
<p class="muted mb-4">
	Heures prévues sur toute l’année, remplacements et rattrapages compris, du point de vue d’un
	élève. Moyenne sur {weeks} semaines d’enseignement, semaines partielles comprises. Une séance de 55
	à 65 minutes compte pour une heure ; pauses et vacances exclues.
</p>
{#if totals.length}
	<StatisticChart
		title="Heures par matière"
		kind="stacked"
		{series}
		labels={names}
		format={formatTeachingHours}
	/>
{:else}<p role="status">Aucune séance dans ce calendrier.</p>{/if}
<p class="help mt-3">
	Pour les matières réservées aux groupes personnalisés, la moyenne porte uniquement sur les élèves
	de ces groupes. Pour les autres matières, elle porte sur la classe entière. Consultez « Points à
	vérifier » pour repérer les écarts entre groupes.
</p>
