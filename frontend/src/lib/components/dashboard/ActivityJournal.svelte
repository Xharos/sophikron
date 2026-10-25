<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { read } from '#lib/dashboard';
	import type { EventPage, EventType } from '#lib/types';
	import ActivityEventRow from './ActivityEventRow.svelte';
	import Icon from '../Icon.svelte';
	let { revision = 0 }: { revision?: number } = $props();
	let types = $state<EventType[]>([]);
	let selectedType = $state('');
	let order = $state('desc');
	let events = $state<EventPage>({ items: [], next_cursor: null });
	let cursors = $state<(string | undefined)[]>([undefined]);
	let ready = $state(false);
	let loading = $state(true);
	let error = $state('');
	let catalogueError = $state('');
	let controller: AbortController | undefined;
	const definitions = $derived(new Map(types.map((item) => [item.code, item])));
	onMount(() => {
		ready = true;
		void loadTypes();
		return () => controller?.abort();
	});
	$effect(() => {
		void revision;
		void selectedType;
		void order;
		if (!ready) return;
		untrack(() => {
			cursors = [undefined];
			void loadPage();
		});
	});
	async function loadTypes(): Promise<void> {
		catalogueError = '';
		try {
			types = (await read<EventType[]>('eventTypes')).sort((a, b) =>
				a.label.localeCompare(b.label, 'fr')
			);
		} catch (cause) {
			catalogueError = (cause as Error).message;
		}
	}
	async function loadPage(cursor?: string): Promise<boolean> {
		controller?.abort();
		const request = new AbortController();
		controller = request;
		loading = true;
		error = '';
		try {
			const result = await read<EventPage>(
				'events',
				{ cursor, limit: 15, event_type: selectedType || undefined, order },
				request.signal
			);
			if (controller !== request) return false;
			events = result;
			return true;
		} catch (cause) {
			if (!request.signal.aborted) error = (cause as Error).message;
			return false;
		} finally {
			if (controller === request) loading = false;
		}
	}
	async function next(): Promise<void> {
		if (loading || !events.next_cursor) return;
		const cursor = events.next_cursor;
		if (await loadPage(cursor)) cursors = [...cursors, cursor];
	}
	async function previous(): Promise<void> {
		if (loading || cursors.length <= 1) return;
		const history = cursors.slice(0, -1);
		if (await loadPage(history.at(-1))) cursors = history;
	}
</script>

<section class="workspace-panel event-panel" aria-labelledby="activity-journal-title">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Le fil de l’établissement</p>
			<h3 id="activity-journal-title" class="title is-4 mb-2">Journal d’activité</h3>
			<p class="muted text-small">Les actions, leurs auteurs et les accès au moment des faits.</p>
		</div>
		<span class="journal-count">15 par page</span>
	</div>
	<div class="journal-filters">
		<div class="field">
			<label class="label" for="event-type">Type d’événement</label>
			<div class="select is-fullwidth">
				<select id="event-type" bind:value={selectedType}
					><option value="">Tous les événements</option>{#each types as type (type.code)}<option
							value={type.code}>{type.label}</option
						>{/each}</select
				>
			</div>
		</div>
		<div class="field">
			<label class="label" for="event-order">Ordre chronologique</label>
			<div class="select is-fullwidth">
				<select id="event-order" bind:value={order}
					><option value="desc">Plus récents d’abord</option><option value="asc"
						>Plus anciens d’abord</option
					></select
				>
			</div>
		</div>
	</div>
	{#if catalogueError}<p class="notification is-warning is-light" role="alert">
			{catalogueError}<button class="button is-small ml-3" onclick={loadTypes}
				>Réessayer les types</button
			>
		</p>{/if}
	{#if error}<p class="notification is-danger is-light" role="alert">
			{error}<button class="button is-small ml-3" onclick={() => loadPage(cursors.at(-1))}
				>Réessayer le journal</button
			>
		</p>{/if}
	<div class="event-list" aria-busy={loading}>
		{#if loading}<p class="loading-state" role="status">Chargement du journal…</p>
		{:else if !error}
			{#each events.items as event (event.id)}<ActivityEventRow
					{event}
					definition={definitions.get(event.event_type)}
				/>{:else}<div class="empty-state">
					<Icon name="clock" size={28} />
					<p>Aucun événement pour cette sélection.</p>
				</div>{/each}
		{/if}
	</div>
	<nav class="list-pagination" aria-label="Pagination du journal">
		<p class="muted text-small" role="status" aria-live="polite">
			Page {cursors.length} · {loading ? 'Chargement…' : `${events.items.length} événement(s)`}
		</p>
		<div class="buttons mb-0">
			<button
				class="button is-light is-small"
				aria-label="Page précédente du journal"
				disabled={loading || cursors.length <= 1}
				onclick={previous}><Icon name="previous" />Précédente</button
			><button
				class="button is-light is-small"
				aria-label="Page suivante du journal"
				disabled={loading || !!error || !events.next_cursor}
				onclick={next}>Suivante<Icon name="next" /></button
			>
		</div>
	</nav>
</section>

<style>
	.journal-filters {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 1rem;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid #eef0f3;
	}
	.journal-filters .field {
		min-width: 0;
	}
	select {
		width: 100%;
	}
	.journal-count {
		border-radius: 999px;
		background: #edf1fa;
		color: #40547c;
		padding: 0.4rem 0.7rem;
		white-space: nowrap;
		font-size: 0.75rem;
	}
	@media (max-width: 600px) {
		.journal-filters {
			grid-template-columns: 1fr;
			gap: 0;
		}
		.list-pagination {
			gap: 0.7rem;
			flex-wrap: wrap;
		}
	}
</style>
