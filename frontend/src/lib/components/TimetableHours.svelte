<script lang="ts">
	import StatisticChart from './statistics/StatisticChart.svelte';
	import {
		blockKinds,
		formatTeachingHours,
		weeklySubjectHours,
		type WeeklyBlock
	} from '#lib/timetable';
	let {
		blocks,
		sessionMinutes,
		subjects
	}: {
		blocks: WeeklyBlock[];
		sessionMinutes: number;
		subjects: { id: number; name: string }[];
	} = $props();
	const totals = $derived(weeklySubjectHours(blocks, sessionMinutes));
	const names = $derived(
		totals.map(
			(row) => subjects.find((subject) => subject.id === row.subjectId)?.name ?? 'Sans matière'
		)
	);
	const series = $derived(
		(['course', 'td', 'tp'] as const).map((kind, index) => ({
			key: kind,
			label: blockKinds[kind],
			color: ['#244BC1', '#2E8B57', '#A34E18'][index],
			values: totals.map((row) => row[kind])
		}))
	);
</script>

<p class="muted mb-4">
	Moyenne hebdomadaire par élève sur le cycle complet, hors khôlles. Une séance de 55 à 65 minutes
	compte pour une heure. Les pauses sont exclues.
</p>
{#if totals.length}
	<StatisticChart
		title="Heures par matière"
		kind="stacked"
		{series}
		labels={names}
		format={formatTeachingHours}
	/>
{:else}<p role="status">Aucune séance de cours, TD ou TP dans cette semaine type.</p>{/if}
<p class="help mt-3">
	Si les groupes ont des volumes différents, le graphique présente leur moyenne. Consultez « Points
	à vérifier » pour repérer les écarts.
</p>
