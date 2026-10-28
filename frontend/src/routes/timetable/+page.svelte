<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto, invalidateAll } from '$app/navigation';
	import Modal from '#lib/components/Modal.svelte';
	import { timetableCommand } from '#lib/timetableClient';
	import type { TimetableAgenda } from '#lib/timetable';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let editing = $state<TimetableAgenda | null>(null);
	let editorOpen = $state(false);
	let deleting = $state<TimetableAgenda | null>(null);
	let name = $state('');
	let promotionId = $state<number | null>(null);
	let busy = $state(false);
	let message = $state('');
	function edit(agenda: TimetableAgenda | null): void {
		editing = agenda;
		name = agenda?.name ?? '';
		promotionId = agenda?.promotion_id ?? null;
		message = '';
		editorOpen = true;
	}
	async function save(): Promise<void> {
		busy = true;
		message = '';
		try {
			await timetableCommand(
				editing ? `calendars/${editing.id}` : 'calendars',
				editing ? 'PUT' : 'POST',
				{
					name,
					promotion_id: promotionId,
					is_paused: editing?.is_paused ?? false,
					expected_revision: editing?.revision ?? null
				}
			);
			editorOpen = false;
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	async function toggle(agenda: TimetableAgenda): Promise<void> {
		busy = true;
		message = '';
		try {
			await timetableCommand(`calendars/${agenda.id}`, 'PUT', {
				name: agenda.name,
				promotion_id: agenda.promotion_id,
				expected_revision: agenda.revision,
				is_paused: !agenda.is_paused
			});
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Modification impossible.';
		} finally {
			busy = false;
		}
	}
	async function remove(): Promise<void> {
		if (!deleting) return;
		busy = true;
		message = '';
		try {
			await timetableCommand(`calendars/${deleting.id}`, 'DELETE', {
				expected_revision: deleting.revision
			});
			deleting = null;
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Suppression impossible.';
		} finally {
			busy = false;
		}
	}
	async function open(agenda: TimetableAgenda): Promise<void> {
		busy = true;
		message = '';
		try {
			const shared =
				data.catalog.common_years?.find(
					(year) =>
						year.settings &&
						year.settings.start <= data.catalog.today &&
						year.settings.end >= data.catalog.today
				) ?? data.catalog.common_years?.find((year) => year.settings);
			if (
				data.catalog.administrator &&
				shared?.settings &&
				!agenda.years.some((year) => year.school_year === shared.school_year)
			)
				await timetableCommand(`calendars/${agenda.id}/years`, 'POST', {
					settings: shared.settings,
					copy_previous: true
				});
			await goto(resolve('/timetable/[id]', { id: String(agenda.id) }));
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Ouverture impossible.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head
	><title>Agendas — {data.establishmentName}</title><meta
		name="description"
		content="Gestion des agendas et des réglages de l’établissement."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container agenda-management">
	<header class="management-heading">
		<div>
			<p class="eyebrow">Emplois du temps</p>
			<h1 class="title is-2">Agendas</h1>
		</div>
		{#if data.catalog.administrator}<div class="buttons">
				<a class="button is-light" href={resolve('/timetable/settings')}>Réglages communs</a><button
					class="button is-primary"
					disabled={busy}
					onclick={() => edit(null)}>Nouvel agenda</button
				>
			</div>{/if}
	</header>
	{#if message && !editorOpen && !deleting}<p class="notification is-danger is-light" role="alert">
			{message}
		</p>{/if}
	{#if !data.catalog.calendars.length}<div class="workspace-panel empty-agendas">
			<h2 class="title is-5">Aucun agenda de promotion</h2>
			<p class="muted">
				{data.catalog.administrator
					? 'Créez un agenda, puis associez-lui une promotion.'
					: 'Les agendas de vos promotions apparaîtront ici.'}
			</p>
		</div>{/if}
	{#if data.catalog.administrator && data.catalog.calendars.some((agenda) => agenda.promotion_id === null)}<p
			class="notification is-warning is-light"
			role="alert"
		>
			Un ou plusieurs agendas n’ont aucune promotion affectée. Vous pouvez les préparer et les
			sauvegarder ; affectez une promotion pour les diffuser aux élèves et enseignants.
		</p>{/if}
	<div class="agenda-list">
		<article class="agenda-row workspace-panel">
			<a class="agenda-open" href={resolve('/timetable/prof')}>
				<span class="agenda-symbol" aria-hidden="true">▦</span>
				<span
					><strong>prof</strong><small>Disponibilités et emplois du temps des enseignants</small
					></span
				>
			</a>
			<span class="tag">Agenda permanent</span>
		</article>
		{#each data.catalog.calendars as agenda (agenda.id)}<article class="agenda-row workspace-panel">
				<button class="agenda-open" disabled={busy} onclick={() => open(agenda)}
					><span class="agenda-symbol" aria-hidden="true">▦</span><span
						><strong>{agenda.name}</strong><small
							>{data.catalog.promotions.find((promotion) => promotion.id === agenda.promotion_id)
								?.name ?? 'Aucune promotion affectée'}</small
						></span
					></button
				>
				<div class="agenda-actions">
					{#if data.catalog.administrator}<label class="pause-switch"
							><input
								type="checkbox"
								role="switch"
								checked={!agenda.is_paused}
								aria-label={`Agenda ${agenda.name} actif`}
								disabled={busy}
								onchange={() => toggle(agenda)}
							/><span class="switch-track" aria-hidden="true"></span><span
								>{agenda.is_paused ? 'En pause' : 'Actif'}</span
							></label
						>
						<button class="button is-small is-light" disabled={busy} onclick={() => edit(agenda)}
							>Modifier</button
						><button
							class="button is-small is-light"
							disabled={busy}
							onclick={() => {
								deleting = agenda;
								message = '';
							}}>Supprimer</button
						>
					{:else if agenda.is_paused}<span class="tag">Diffusion figée</span>{/if}
				</div>
			</article>{/each}
	</div>
</section>
{#if editorOpen}<Modal
		title={editing ? 'Modifier l’agenda' : 'Nouvel agenda'}
		{busy}
		onclose={() => (editorOpen = false)}
	>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void save();
			}}
		>
			{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
			<label class="label" for="agenda-name">Nom de l’agenda</label><input
				id="agenda-name"
				class="input mb-4"
				bind:value={name}
				required
				maxlength="100"
			/>
			<label class="label" for="agenda-promotion">Promotion affectée</label>
			<div class="select is-fullwidth mb-5">
				<select id="agenda-promotion" bind:value={promotionId}
					><option value={null}>Aucune</option
					>{#each data.catalog.promotions as promotion (promotion.id)}<option value={promotion.id}
							>{promotion.name}</option
						>{/each}</select
				>
			</div>
			<button class="button is-primary" disabled={busy}>Enregistrer</button>
		</form>
	</Modal>{/if}
{#if deleting}<Modal title="Supprimer l’agenda" {busy} onclose={() => (deleting = null)}>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<p>
			Retirer « {deleting.name} » de la liste et des abonnements ? Les données historiques seront conservées.
		</p>
		<div class="buttons mt-5">
			<button class="button is-danger" disabled={busy} onclick={remove}>Supprimer l’agenda</button
			><button class="button is-light" disabled={busy} onclick={() => (deleting = null)}
				>Annuler</button
			>
		</div>
	</Modal>{/if}

<style>
	.agenda-management {
		max-width: 1100px;
	}
	.management-heading,
	.agenda-row,
	.agenda-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1.25rem;
	}
	.management-heading {
		margin: 1rem 0 2rem;
		flex-wrap: wrap;
	}
	.agenda-list {
		display: grid;
		gap: 1rem;
	}
	.agenda-row {
		padding: 1.2rem 1.4rem;
	}
	.agenda-open {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex: 1;
		text-align: left;
		border: 0;
		color: inherit;
		background: none;
		cursor: pointer;
		padding: 0;
	}
	.agenda-open strong {
		display: block;
		font-size: 1.1rem;
	}
	small {
		display: block;
		color: var(--color-muted);
		margin-top: 0.25rem;
	}
	.agenda-symbol {
		color: var(--color-primary);
		background: var(--color-soft);
		border-radius: 12px;
		padding: 0.5rem 0.8rem;
		font-size: 1.7rem;
	}
	.pause-switch {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.pause-switch input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
	}
	.switch-track {
		pointer-events: none;
		width: 36px;
		height: 22px;
		border-radius: 20px;
		background: var(--color-border);
		position: relative;
	}
	.switch-track::after {
		content: '';
		position: absolute;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--color-surface);
		left: 3px;
		top: 3px;
		transition: transform 0.15s;
	}
	.pause-switch input:checked + .switch-track {
		background: var(--color-primary);
	}
	.pause-switch input:checked + .switch-track::after {
		transform: translateX(14px);
	}
	.pause-switch input:focus-visible + .switch-track {
		outline: 3px solid var(--color-primary);
		outline-offset: 3px;
	}
	.empty-agendas {
		padding: 3rem;
		text-align: center;
	}
	@media (max-width: 700px) {
		.agenda-row {
			align-items: start;
			flex-direction: column;
		}
		.agenda-actions {
			width: 100%;
			flex-wrap: wrap;
			gap: 0.7rem;
		}
	}
</style>
