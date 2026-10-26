<script lang="ts">
	import { command } from '#lib/dashboard';
	import { lessonDate } from '#lib/lessons';
	import { eventLabels, type PublicSite, type Timeline, type TimelineEvent } from '#lib/site';
	import Modal from '../Modal.svelte';
	import ColorPicker from '../ColorPicker.svelte';
	import TagSelector from '../TagSelector.svelte';
	let { site, onchanged }: { site: PublicSite; onchanged: () => Promise<void> } = $props();
	let editor = $state<'timeline' | 'event' | null>(null),
		selected = $state<Timeline | TimelineEvent | null>(null);
	let name = $state(''),
		start = $state(''),
		end = $state(''),
		color = $state('#244bc1');
	let kind = $state<TimelineEvent['kind']>('other'),
		timelineIds = $state<number[]>([]);
	let busy = $state(false),
		message = $state('');
	let removing = $state<{ value: Timeline | TimelineEvent; event: boolean } | null>(null);
	function edit(event: boolean, value: Timeline | TimelineEvent | null = null): void {
		selected = value;
		editor = event ? 'event' : 'timeline';
		name = value?.name ?? '';
		start = value?.starts_on ?? site.today;
		end = value?.ends_on ?? site.today;
		color = value?.color ?? '#244bc1';
		kind = value && 'kind' in value ? value.kind : 'other';
		timelineIds = value && 'timeline_ids' in value ? [...value.timeline_ids] : [];
		message = '';
	}
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		busy = true;
		message = '';
		try {
			const data = {
				name,
				starts_on: start,
				ends_on: end,
				color,
				...(editor === 'event' ? { kind, timeline_ids: timelineIds } : {}),
				...(selected ? { expected_version: selected.version } : {})
			};
			await command(
				`${selected ? 'update' : 'create'}${editor === 'event' ? 'Event' : 'Timeline'}`,
				{ id: selected?.id, data }
			);
			editor = null;
			await onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function remove(): Promise<void> {
		if (!removing) return;
		busy = true;
		message = '';
		try {
			await command(removing.event ? 'deleteEvent' : 'deleteTimeline', {
				id: removing.value.id,
				data: { expected_version: removing.value.version }
			});
			removing = null;
			await onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<section class="workspace-panel mt-5">
	<div class="section-intro">
		<div>
			<h3 class="title is-4">Timelines annuelles</h3>
			<p class="muted">Une barre par année ou parcours. Les événements peuvent être partagés.</p>
		</div>
		<button class="button is-primary" onclick={() => edit(false)}>Ajouter une timeline</button>
	</div>
	{#if !site.timelines.length}<p class="muted">
			Aucune timeline. Ajoutez une première barre pour organiser l’année.
		</p>{/if}
	{#each site.timelines as bar (bar.id)}<div class="calendar-row">
			<div>
				<strong>{bar.name}</strong>
				<p class="muted">{lessonDate(bar.starts_on)} — {lessonDate(bar.ends_on)}</p>
			</div>
			<button class="button is-light is-small" onclick={() => edit(false, bar)}>Modifier</button
			><button
				class="button is-danger is-light is-small"
				onclick={() => {
					removing = { value: bar, event: false };
					message = '';
				}}>Supprimer</button
			>
		</div>{/each}
</section>
<section class="workspace-panel mt-5">
	<div class="section-intro">
		<div>
			<h3 class="title is-4">Vacances et événements</h3>
			<p class="muted">Les informations enregistrées sont visibles publiquement sur l’accueil.</p>
		</div>
		<button class="button is-primary" disabled={!site.timelines.length} onclick={() => edit(true)}
			>Ajouter un événement</button
		>
	</div>
	{#if !site.events.length}<p class="muted">Aucun événement.</p>{/if}
	{#each site.events as item (item.id)}<div class="calendar-row">
			<div>
				<strong>{item.name}</strong> · {eventLabels[item.kind]}
				<p class="muted">{lessonDate(item.starts_on)} — {lessonDate(item.ends_on)}</p>
				<p class="help">
					{site.timelines
						.filter((bar) => item.timeline_ids.includes(bar.id))
						.map((bar) => bar.name)
						.join(', ')}
				</p>
			</div>
			<button class="button is-light is-small" onclick={() => edit(true, item)}>Modifier</button
			><button
				class="button is-danger is-light is-small"
				onclick={() => {
					removing = { value: item, event: true };
					message = '';
				}}>Supprimer</button
			>
		</div>{/each}
</section>
{#if message && !editor && !removing}<p class="notification is-danger is-light" role="alert">
		{message}
	</p>{/if}
{#if editor}<Modal
		title={`${selected ? 'Modifier' : 'Créer'} ${editor === 'event' ? 'un événement' : 'une timeline'}`}
		{busy}
		onclose={() => {
			if (!busy) editor = null;
		}}
	>
		<form onsubmit={save}>
			{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
			<div class="field">
				<label class="label" for="calendar-name">Intitulé</label><input
					id="calendar-name"
					class="input"
					bind:value={name}
					maxlength="100"
					required
				/>
			</div>
			<div class="form-grid">
				<div class="field">
					<label class="label" for="calendar-start">Début inclus</label><input
						id="calendar-start"
						class="input"
						type="date"
						bind:value={start}
						required
					/>
				</div>
				<div class="field">
					<label class="label" for="calendar-end">Fin incluse</label><input
						id="calendar-end"
						class="input"
						type="date"
						bind:value={end}
						min={start}
						required
					/>
				</div>
			</div>
			{#if editor === 'event'}<div class="field">
					<label class="label" for="calendar-kind">Type</label>
					<div class="select is-fullwidth">
						<select id="calendar-kind" bind:value={kind}
							>{#each Object.entries(eventLabels) as [value, label] (value)}<option {value}
									>{label}</option
								>{/each}</select
						>
					</div>
				</div>
			{/if}
			{#if editor === 'event' && kind === 'holiday'}
				<p class="help mb-4">
					<span class="holiday-preview" style:background={site.settings.holiday_color}></span>
					Couleur commune aux vacances. Modifiez-la dans la configuration du site.
				</p>
			{:else}<ColorPicker id="calendar-color" bind:value={color} disabled={busy} />{/if}
			{#if editor === 'event'}
				<div class="field">
					<TagSelector
						legend="Timelines concernées"
						bind:selected={timelineIds}
						disabled={busy}
						options={site.timelines.map((bar) => ({
							value: bar.id,
							label: bar.name,
							color: bar.color
						}))}
					/>
					<p class="help">
						Choisissez une ou plusieurs barres. Les dates de l’événement doivent être comprises dans
						chacune.
					</p>
				</div>{/if}
			<div class="dialog-actions">
				<button
					type="button"
					class="button is-light"
					disabled={busy}
					onclick={() => (editor = null)}>Annuler</button
				><button
					class="button is-primary"
					class:is-loading={busy}
					disabled={busy || (editor === 'event' && !timelineIds.length)}>Enregistrer</button
				>
			</div>
		</form>
	</Modal>{/if}
{#if removing}<Modal
		title="Supprimer cet élément du calendrier ?"
		{busy}
		onclose={() => {
			if (!busy) removing = null;
		}}
	>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<p>
			Supprimer « {removing.value.name} » ? {removing.event
				? 'L’événement sera retiré de toutes ses barres.'
				: 'Les événements communs aux autres barres seront conservés. Ceux qui concernent uniquement cette barre seront supprimés.'}
		</p>
		<div class="dialog-actions">
			<button class="button is-light" disabled={busy} onclick={() => (removing = null)}
				>Annuler</button
			><button class="button is-danger" class:is-loading={busy} disabled={busy} onclick={remove}
				>Supprimer</button
			>
		</div>
	</Modal>{/if}

<style>
	.section-intro > .button {
		display: inline-flex;
	}
	.holiday-preview {
		display: inline-block;
		width: 0.75rem;
		height: 0.75rem;
		border-radius: 50%;
		vertical-align: middle;
		margin-right: 0.4rem;
	}
	.calendar-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.6rem;
		padding: 1rem 0;
		border-bottom: var(--border-thin);
	}
	.calendar-row > div {
		flex: 1;
		min-width: 180px;
	}
</style>
