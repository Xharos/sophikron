<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { read } from '#lib/dashboard';
	import type { EventPage, EventType } from '#lib/types';
	import ActivityEventRow from './ActivityEventRow.svelte';
	import Icon from '../Icon.svelte';
	import EventAccountPicker from './EventAccountPicker.svelte';
	import type { DirectoryUser } from '#lib/types';
	let {
		revision = 0,
		userId,
		compact = false
	}: { revision?: number; userId?: number; compact?: boolean } = $props();
	let pageSize = $state(5);
	let family = $state('');
	let picking = $state(false);
	let eventMenu = $state<HTMLDetailsElement>();
	function selectFilter(nextFamily: string, nextType = ''): void {
		family = nextFamily;
		selectedType = nextType;
		if (eventMenu) {
			eventMenu.open = false;
			eventMenu.querySelector('summary')?.focus();
		}
	}
	let selectedUser = $state<DirectoryUser | null>(null);
	const families = [
		{ code: 'accounts', label: 'Comptes' },
		{ code: 'promotions', label: 'Promos et groupes' },
		{ code: 'lessons', label: 'Cours' },
		{ code: 'administration', label: 'Administration' }
	];
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
		void pageSize;
		void family;
		void selectedUser;
		void userId;
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
				{
					cursor,
					limit: compact ? 5 : pageSize,
					event_type: selectedType || undefined,
					family: family || undefined,
					user_id: userId ?? selectedUser?.id,
					order
				},
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

<section
	class="workspace-panel event-panel"
	aria-labelledby={compact ? `user-journal-${userId}` : 'activity-journal-title'}
>
	<div class="panel-heading">
		<div>
			{#if !compact}<p class="eyebrow">Le fil de l’établissement</p>{/if}
			<h3
				id={compact ? `user-journal-${userId}` : 'activity-journal-title'}
				class="title is-4 mb-2"
			>
				{compact ? 'Dernières activités du compte' : 'Journal d’activité'}
			</h3>
			<p class="muted text-small">
				{compact
					? 'Les cinq derniers événements comme auteur ou cible.'
					: 'Les actions, leurs auteurs et les accès au moment des faits.'}
			</p>
		</div>
		{#if !compact}<div class="select is-small">
				<select aria-label="Événements par page" bind:value={pageSize}
					>{#each [5, 15, 50] as size (size)}<option value={size}>{size} par page</option
						>{/each}</select
				>
			</div>{/if}
	</div>
	{#if !compact}
		<div class="journal-filters">
			<details class="event-menu" bind:this={eventMenu}>
				<summary class="event-trigger"
					><Icon name="clock" size={14} /><span
						>{types.find((t) => t.code === selectedType)?.label ??
							families.find((f) => f.code === family)?.label ??
							'Tous les événements'}</span
					><Icon name="next" size={12} /></summary
				>
				<div class="event-menu-content">
					<button
						class="event-option"
						aria-pressed={!family && !selectedType}
						onclick={() => selectFilter('')}>Tous les événements</button
					>
					{#each families as group (group.code)}<details class="event-family">
							<summary><span>{group.label}</span><Icon name="next" size={11} /></summary><button
								class="event-option family-option"
								aria-pressed={family === group.code && !selectedType}
								onclick={() => selectFilter(group.code)}>Toute la catégorie</button
							>
							{#each types.filter((t) => t.family === group.code) as type (type.code)}<button
									class="event-option"
									aria-pressed={selectedType === type.code}
									onclick={() => selectFilter(group.code, type.code)}>{type.label}</button
								>{/each}
						</details>{/each}
				</div>
			</details>
			<button class="button is-light is-small account-filter" onclick={() => (picking = true)}
				><Icon name="profile" />{selectedUser
					? selectedUser.first_name + ' ' + selectedUser.last_name
					: 'Tous les membres'}</button
			>
			<div
				class="buttons has-addons mb-0 order-filter"
				role="group"
				aria-label="Ordre chronologique"
			>
				<button
					class="button is-small"
					class:is-primary={order === 'desc'}
					aria-pressed={order === 'desc'}
					onclick={() => (order = 'desc')}>Plus récents</button
				><button
					class="button is-small"
					class:is-primary={order === 'asc'}
					aria-pressed={order === 'asc'}
					onclick={() => (order = 'asc')}>Plus anciens</button
				>
			</div>
		</div>{/if}
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
	{#if !compact}<nav class="list-pagination" aria-label="Pagination du journal">
			<p class="muted text-small" role="status" aria-live="polite">
				Page {cursors.length} · {loading
					? 'Chargement…'
					: `${events.items.length} événement${events.items.length === 1 ? '' : 's'}`}
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
		</nav>{/if}
</section>

{#if picking}<EventAccountPicker
		selected={selectedUser}
		onclose={() => (picking = false)}
		onapply={(user) => {
			selectedUser = user;
			picking = false;
		}}
	/>{/if}

<style>
	.event-menu {
		position: relative;
		flex: 1 1 13rem;
		min-width: 0;
		max-width: 100%;
	}
	.event-trigger,
	.event-family > summary {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		cursor: pointer;
		list-style: none;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	.event-trigger {
		padding: 0.45rem 0.65rem;
		border: var(--border-thin);
		border-radius: var(--radius-small);
		background: var(--color-subtle);
		color: var(--color-primary);
		font-size: 0.78rem;
		font-weight: 600;
	}
	.event-trigger span {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.event-trigger:hover {
		background: var(--color-soft);
	}
	summary:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 2px;
	}
	details[open] > summary > :global(.app-icon:last-child) {
		transform: rotate(90deg);
	}
	.event-family > summary {
		padding: 0.45rem 0.55rem;
		font-size: 0.78rem;
		font-weight: 650;
		color: var(--color-ink);
		border-radius: 0.35rem;
	}
	.event-family > summary:hover {
		background: var(--color-subtle);
	}
	.event-family + .event-family {
		border-top: var(--border-thin);
	}
	.event-family {
		padding-block: 0.15rem;
	}
	.event-family .event-option {
		padding-left: 1rem;
	}
	.event-family .family-option {
		font-weight: 650;
		color: var(--color-primary);
	}
	.event-option {
		--action-bg: transparent;
		--action-fg: var(--color-ink);
		--action-border: transparent;
		--action-hover: var(--color-soft);
		--action-hover-shadow: none;
		display: block;
		width: 100%;
		min-width: 0;
		padding: 0.4rem 0.55rem;
		text-align: left;
		font-size: 0.76rem;
		font-weight: 400;
		line-height: 1.4;
		white-space: normal;
		overflow-wrap: anywhere;
	}
	.event-option[aria-pressed='true'] {
		--action-bg: var(--color-soft);
		--action-fg: var(--color-primary);
		--action-hover: var(--color-soft);
		font-weight: 650;
	}
	.event-menu-content {
		box-sizing: border-box;
		position: absolute;
		z-index: 5;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: 0.5rem;
		padding: 0.35rem;
		width: 100%;
		inset-inline-start: 0;
		top: calc(100% + 0.3rem);
		max-height: min(22rem, 55dvh);
		overflow-y: auto;
		overflow-x: hidden;
		box-shadow: var(--shadow-panel);
	}
	.journal-filters {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid var(--color-border);
	}
	select {
		width: 100%;
	}
	.account-filter {
		max-width: 100%;
		white-space: normal;
		height: auto;
		min-height: 2rem;
		overflow-wrap: anywhere;
	}
	.order-filter {
		flex-wrap: nowrap;
		gap: 0;
	}
	.order-filter .button {
		font-size: 0.75rem;
		padding-inline: 0.6rem;
	}
	@media (max-width: 600px) {
		.journal-filters {
			gap: 0.5rem;
		}
		.list-pagination {
			gap: 0.7rem;
			flex-wrap: wrap;
		}
	}
</style>
