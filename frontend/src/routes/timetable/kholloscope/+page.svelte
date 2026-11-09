<script lang="ts">
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import KholloscopePreparation from '#lib/components/KholloscopePreparation.svelte';
	import KholleSettings from '#lib/components/KholleSettings.svelte';
	import KholleWishes from '#lib/components/KholleWishes.svelte';
	import KholloscopeGeneration from '#lib/components/KholloscopeGeneration.svelte';
	import KholloscopeRevision from '#lib/components/KholloscopeRevision.svelte';
	import type { GenerationView } from '#lib/kholloscopeGeneration';
	import { kholleLoad, kholleDuration } from '#lib/kholle';
	import { kholloscopeSteps } from '#lib/kholleWishes';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let dirtyWishes = $state(false);
	let wishesReady = $state(true);
	let wishesEditor = $state<{ save: () => Promise<boolean> }>();
	let dirtyGeneration = $state(false);
	let generation = $state.raw<GenerationView | null>(null);
	$effect(() => {
		generation = data.generation;
	});
	let wishesNotice = $state('');
	let pendingVolumes = $state<Record<number, boolean>>({});
	const published = $derived(!!generation?.run?.result?.applied);
	const canPrepare = $derived(data.canWrite && !published);
	const tabTitle = $derived(
		kholloscopeSteps.find((step) => step.id === data.tab)?.label ?? 'Kholloscope'
	);
	const calendars = $derived(
		data.overview.calendars.map((calendar) => ({
			...calendar,
			load: kholleLoad(
				calendar.settings.subjects.map((subject) => subject.minutes),
				calendar.group_count,
				calendar.weeks
			)
		}))
	);
	const total = $derived(calendars.reduce((sum, calendar) => sum + calendar.load.total, 0));
	const groups = $derived(calendars.reduce((sum, calendar) => sum + calendar.group_count, 0));
	const weekly = $derived(
		calendars.reduce((sum, calendar) => sum + (calendar.load.weekly ?? 0), 0)
	);
	const decimal = (value: number): string =>
		value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	const needs = $derived.by(() => {
		if (data.overview.errors.length || calendars.some((calendar) => !calendar.weeks)) return null;
		const result: Record<number, number> = {};
		for (const calendar of calendars)
			for (const subject of calendar.settings.subjects) {
				result[subject.subject_id] =
					(result[subject.subject_id] ?? 0) +
					(subject.minutes * calendar.group_count) / calendar.weeks / 60;
			}
		return result;
	});
</script>

<svelte:head
	><title>{tabTitle} — {data.establishmentName}</title><meta
		name="description"
		content="Volumes de khôlle et charge prévisionnelle des équipes pédagogiques."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
{#key data.overview.school_year}<KholloscopePreparation
		{data}
		{generation}
		editorNotice={data.tab === 'wishes' ? wishesNotice : ''}
		dirtyInputs={dirtyWishes || dirtyGeneration || Object.values(pendingVolumes).some(Boolean)}
		{wishesReady}
		saveWishes={() => wishesEditor?.save() ?? Promise.resolve(false)}
	>
		<section class="kholloscope">
			<h1 class="title is-3 mb-5">{tabTitle}</h1>
			{#if data.tab === 'volumes'}
				{#if data.overview.errors.length}
					<div class="notification is-warning is-light" role="alert">
						{#each data.overview.errors as problem (problem)}<p>{problem}</p>{/each}
					</div>
				{:else}
					<div class="summary workspace-panel mb-5" role="status">
						<div><small>Calendriers</small><strong>{calendars.length}</strong></div>
						<div><small>Groupes de khôlle</small><strong>{groups}</strong></div>
						<div>
							<small>Volume total de l’équipe</small><strong>{kholleDuration(total)}</strong>
						</div>
						<div>
							<small>Somme des moyennes hebdomadaires</small><strong
								>{decimal(weekly)} h/semaine</strong
							>
						</div>
					</div>

					<p class="help mb-5">
						Chaque moyenne utilise la période propre au calendrier. Leur somme ne représente pas la
						charge d’une semaine précise.
					</p>
				{/if}
				<div class="calendar-grid">
					{#each data.catalog.calendars.filter((calendar) => !calendar.is_archived && calendar.years.some((year) => year.school_year === data.overview.school_year)) as calendar (calendar.id)}
						<article class="workspace-panel">
							<h2 class="title is-4">{calendar.name}</h2>
							{#if calendar.promotion_id === null}
								<p class="notification is-warning is-light">
									Affectez une promotion à cet agenda avant de définir ses khôlles.
									<a href={resolve('/timetable')}>Gérer les agendas</a>
								</p>
							{:else}
								<KholleSettings
									calendarId={calendar.id}
									subjects={data.catalog.subjects}
									onsaved={invalidateAll}
									canWrite={canPrepare}
									ondirty={(value) => {
										pendingVolumes[calendar.id] = value;
									}}
								/>
							{/if}
						</article>
					{/each}
				</div>
			{:else if (data.tab === 'generation' || data.tab === 'groups') && !data.accessError && data.generation && data.overview.school_year !== null}
				{#key `${data.overview.school_year}-${data.tab}`}<KholloscopeGeneration
						year={data.overview.school_year}
						initial={data.generation}
						catalog={data.catalog}
						mode={data.tab}
						canWrite={data.canWrite}
						ondirty={(value) => {
							dirtyGeneration = value;
						}}
						onupdate={(value) => {
							generation = value;
						}}
					/>{/key}
			{:else if data.tab === 'revision' && !data.accessError}
				{#if data.revision && data.overview.school_year !== null}
					{#key data.overview.school_year}<KholloscopeRevision
							initial={data.revision}
							year={data.overview.school_year}
							catalog={data.catalog}
							canWrite={data.canWrite}
						/>{/key}
				{/if}
			{:else if data.tab === 'wishes' && !data.accessError && data.wishes}
				{#key data.wishes.school_year}<KholleWishes
						initial={data.wishes}
						showHeading={false}
						canWrite={canPrepare}
						bind:this={wishesEditor}
						onvalidity={(valid) => (wishesReady = valid)}
						onnotice={(message) => (wishesNotice = message)}
						{needs}
						ondirty={(value) => {
							dirtyWishes = value;
						}}
						onsaved={invalidateAll}
					/>{/key}
			{/if}
		</section>
	</KholloscopePreparation>{/key}

<style>
	.kholloscope {
		max-width: 1200px;
	}
	.summary {
		display: flex;
		flex-wrap: wrap;
		gap: 1.5rem;
		background: var(--color-paper);
		color: var(--color-ink);
	}
	.summary div {
		flex: 1 1 10rem;
	}
	small {
		display: block;
		color: var(--color-muted);
		margin-bottom: 0.4rem;
	}
	.summary strong {
		font-size: 1.4rem;
		color: var(--color-ink);
	}
	.calendar-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr));
		gap: 1.5rem;
	}
</style>
