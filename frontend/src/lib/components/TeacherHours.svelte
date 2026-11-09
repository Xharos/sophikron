<script lang="ts">
	import {
		blockKinds,
		formatTeachingHours,
		mondayOf,
		shiftTimetableDate,
		type TimetableEvent
	} from '#lib/timetable';
	import { teacherSubjectHours, teacherCalendarHours } from '#lib/teacherTimetable';
	import StatisticChart from './statistics/StatisticChart.svelte';
	let {
		events,
		sessionMinutes,
		subjects,
		weekStart,
		schoolYear,
		selection
	}: {
		events: TimetableEvent[];
		sessionMinutes: number;
		subjects: { id: number; name: string }[];
		weekStart: string;
		schoolYear: number;
		selection: string;
	} = $props();
	let period = $state<'week' | 'year'>('week');
	let breakdown = $state<'subject' | 'calendar'>('subject');
	const monday = $derived(mondayOf(weekStart));
	const periodEvents = $derived(
		period === 'year'
			? events
			: events.filter(
					(event) =>
						event.start.slice(0, 10) >= monday &&
						event.start.slice(0, 10) < shiftTimetableDate(monday, 7)
				)
	);
	const totals = $derived(teacherSubjectHours(periodEvents, sessionMinutes));
	const rows = $derived(teacherCalendarHours(periodEvents, sessionMinutes));
	const grandTotal = $derived(totals.reduce((sum, row) => sum + row.total, 0));
	function subjectName(id: number | null): string {
		return subjects.find((subject) => subject.id === id)?.name ?? 'Sans matière';
	}
	const chartRows = $derived(
		breakdown === 'subject'
			? totals.map((row) => ({ ...row, label: subjectName(row.subjectId) }))
			: rows.map((row) => ({ ...row, label: row.label + ' · ' + subjectName(row.subjectId) }))
	);
	const series = $derived(
		(['course', 'td', 'tp', 'kholle'] as const).map((kind, index) => ({
			key: kind,
			label: blockKinds[kind],
			color: ['#244BC1', '#2E8B57', '#A34E18', '#9747BB'][index],
			values: chartRows.map((row) => row[kind])
		}))
	);
</script>

<section aria-label="Heures des enseignants">
	<div class="buttons mb-4" role="group" aria-label="Période des heures">
		<button
			class="button"
			class:is-primary={period === 'week'}
			aria-pressed={period === 'week'}
			onclick={() => (period = 'week')}>Semaine affichée</button
		>
		<button
			class="button"
			class:is-primary={period === 'year'}
			aria-pressed={period === 'year'}
			onclick={() => (period = 'year')}>Total sur l’année</button
		>
	</div>
	<div class="hours-summary mb-4">
		<div>
			<strong>{selection}</strong>
			<p class="muted">
				{period === 'week'
					? 'Semaine du ' + monday
					: 'Année scolaire ' + schoolYear + '/' + (schoolYear + 1)}
			</p>
		</div>
		<div class="hours-total">
			<span>Total des séances affectées</span><strong>{formatTeachingHours(grandTotal)}</strong>
		</div>
	</div>
	<p class="muted mb-4">
		Cours, TD, TP et khôlles, remplacements compris. Les heures sont comptées une fois par séance,
		sans pondération par les groupes d’élèves.
	</p>
	{#if totals.length}
		<div class="buttons has-addons mb-4" role="group" aria-label="Répartition des heures">
			<button
				class="button is-small"
				class:is-primary={breakdown === 'subject'}
				aria-pressed={breakdown === 'subject'}
				onclick={() => (breakdown = 'subject')}>Par matière</button
			>
			<button
				class="button is-small"
				class:is-primary={breakdown === 'calendar'}
				aria-pressed={breakdown === 'calendar'}
				onclick={() => (breakdown = 'calendar')}>Par calendrier</button
			>
		</div>
		<StatisticChart
			title={breakdown === 'subject' ? 'Heures par matière' : 'Heures par calendrier et matière'}
			kind="stacked"
			{series}
			labels={chartRows.map((row) => row.label)}
			format={formatTeachingHours}
		/>
	{:else}
		<p class="notification is-light" role="status">
			Aucune séance affectée à la sélection {period === 'week'
				? 'pendant cette semaine'
				: 'sur cette année scolaire'}.
		</p>
	{/if}
</section>

<style>
	section {
		min-width: 0;
	}
	.hours-summary {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		padding: 1rem;
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		background: var(--color-paper);
	}
	.hours-total {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
	}
	.hours-total span {
		font-size: 0.8rem;
		color: var(--color-muted);
	}
	.hours-total strong {
		font-size: 1.5rem;
		color: var(--color-primary);
	}
	p {
		font-size: 0.85rem;
	}
</style>
