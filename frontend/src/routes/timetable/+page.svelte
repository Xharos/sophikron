<script lang="ts">
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import Modal from '#lib/components/Modal.svelte';
	import TimetableSettingsEditor from '#lib/components/TimetableSettings.svelte';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		defaultTimetableSettings,
		currentSchoolYear,
		preferredSchoolYear,
		type TimetableAgenda,
		type TimetableSettings
	} from '#lib/timetable';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let editing = $state<TimetableAgenda | null>(null);
	let editorOpen = $state(false);
	let name = $state('');
	let promotionId = $state<number | null>(null);
	let schoolYear = $state(0);
	let settings = $state<TimetableSettings>(defaultTimetableSettings(2026));
	let busy = $state(false);
	let message = $state('');
	let archives = $state(false);
	let detachPromotion = $state(false);
	let pending = $state<{
		agenda: TimetableAgenda;
		action: 'save' | 'toggle' | 'archive' | 'restore';
	} | null>(null);
	const agendas = $derived(
		data.catalog.calendars.filter((item) => !!item.is_archived === archives)
	);
	function edit(agenda: TimetableAgenda | null): void {
		editing = agenda;
		name = agenda?.name ?? '';
		promotionId = agenda?.promotion_id ?? null;
		schoolYear = preferredSchoolYear(
			(data.catalog.common_years ?? []).filter(
				(year) => year.school_year >= currentSchoolYear(data.catalog.today)
			),
			data.catalog.today
		);
		settings = defaultTimetableSettings(schoolYear || new Date().getFullYear());
		message = '';
		editorOpen = true;
	}
	async function save(confirmed = false): Promise<void> {
		if (editing && !confirmed) {
			pending = { agenda: editing, action: 'save' };
			return;
		}
		busy = true;
		message = '';
		try {
			await timetableCommand(
				editing ? 'calendars/' + editing.id : 'calendars',
				editing ? 'PUT' : 'POST',
				{
					name,
					promotion_id: promotionId,
					is_paused: editing?.is_paused ?? true,
					expected_revision: editing?.revision ?? null,
					confirmed_live: confirmed,
					confirmed_assignment: confirmed,
					...(!editing ? { school_year: schoolYear, settings } : {})
				}
			);
			pending = null;
			editorOpen = false;
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	async function confirm(): Promise<void> {
		if (!pending) return;
		if (pending.action === 'save') {
			await save(true);
			return;
		}
		const { agenda, action } = pending;
		busy = true;
		message = '';
		try {
			if (action === 'toggle')
				await timetableCommand('calendars/' + agenda.id, 'PUT', {
					name: agenda.name,
					promotion_id: agenda.promotion_id,
					is_paused: !agenda.is_paused,
					expected_revision: agenda.revision,
					confirmed_live: true
				});
			else
				await timetableCommand('calendars/' + agenda.id + '/' + action, 'POST', {
					expected_revision: agenda.revision,
					confirmed_live: true,
					detach_promotion: action === 'restore' ? detachPromotion : undefined
				});
			pending = null;
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Modification impossible.';
		} finally {
			busy = false;
		}
	}
	function ask(agenda: TimetableAgenda, action: 'toggle' | 'archive' | 'restore'): void {
		message = '';
		detachPromotion =
			action === 'restore' &&
			agenda.promotion_id !== null &&
			data.catalog.calendars.some(
				(item) => !item.is_archived && item.promotion_id === agenda.promotion_id
			);
		pending = { agenda, action };
	}
</script>

<svelte:head
	><title>Agendas — {data.establishmentName}</title><meta
		name="description"
		content="Emplois du temps annuels et diffusion des calendriers."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container agenda-management">
	<header class="management-heading">
		<div>
			<p class="eyebrow">Emplois du temps</p>
			<h1 class="title is-2">Agendas</h1>
		</div>
		{#if data.catalog.administrator}<div class="buttons">
				<a class="button is-light" href={resolve('/timetable/settings')}
					>Salles et années scolaires</a
				><button class="button is-primary" disabled={busy} onclick={() => edit(null)}
					>Nouvel agenda</button
				>
			</div>{/if}
	</header>
	{#if data.catalog.administrator}<div class="buttons mb-5">
			<button class="button" class:is-primary={!archives} onclick={() => (archives = false)}
				>Actifs</button
			><button class="button" class:is-primary={archives} onclick={() => (archives = true)}
				>Archives</button
			>
		</div>{/if}
	{#if message && !editorOpen && !pending}<p class="notification is-danger is-light" role="alert">
			{message}
		</p>{/if}
	<div class="agenda-list">
		<article class="agenda-row workspace-panel">
			<a class="agenda-open" href={resolve('/timetable/prof')}
				><span class="agenda-symbol" aria-hidden="true">▦</span><span
					><strong>prof</strong><small>Disponibilités et emplois du temps des enseignants</small
					></span
				></a
			><span class="tag">Agenda permanent</span>
		</article>
		{#each agendas as agenda (agenda.id)}<article class="agenda-row workspace-panel">
				<a class="agenda-open" href={resolve('/timetable/[id]', { id: String(agenda.id) })}
					><span class="agenda-symbol" aria-hidden="true">▦</span><span
						><strong>{agenda.name}</strong><small
							>{agenda.years[0]?.school_year}/{(agenda.years[0]?.school_year ?? 0) + 1} · {data.catalog.promotions.find(
								(p) => p.id === agenda.promotion_id
							)?.name ?? 'Aucune promotion affectée'}</small
						></span
					></a
				>
				{#if data.catalog.administrator}<div class="agenda-actions">
						{#if agenda.is_archived}<span class="tag">Archive · lecture seule</span><button
								class="button is-small is-light"
								disabled={busy}
								onclick={() => ask(agenda, 'restore')}>Réactiver</button
							>{:else}
							<label class="pause-switch"
								><input
									type="checkbox"
									role="switch"
									checked={!agenda.is_paused}
									aria-label={'Diffuser aux élèves ' + agenda.name}
									disabled={busy || agenda.promotion_id === null}
									onclick={(event) => {
										event.preventDefault();
										ask(agenda, 'toggle');
									}}
								/><span class="switch-track" aria-hidden="true"></span><span
									>{agenda.is_paused ? 'Diffusion élèves coupée' : 'Diffusé aux élèves'}</span
								></label
							>
							<button class="button is-small is-light" disabled={busy} onclick={() => edit(agenda)}
								>Modifier</button
							><button
								class="button is-small is-light"
								disabled={busy}
								onclick={() => ask(agenda, 'archive')}>Archiver</button
							>{/if}
					</div>{/if}
			</article>{/each}
		{#if !agendas.length}<p class="workspace-panel empty-agendas">
				{archives ? 'Aucun calendrier archivé.' : 'Aucun calendrier de promotion.'}
			</p>{/if}
	</div>
</section>
{#if editorOpen}<Modal
		title={editing ? 'Modifier l’agenda' : 'Nouvel agenda'}
		{busy}
		onclose={() => (editorOpen = false)}
		><form
			onsubmit={(event) => {
				event.preventDefault();
				void save();
			}}
		>
			{#if message && !pending}<p class="notification is-danger is-light" role="alert">
					{message}
				</p>{/if}
			<label class="label" for="agenda-name">Nom unique</label><input
				id="agenda-name"
				class="input mb-4"
				bind:value={name}
				required
				maxlength="100"
			/>
			<label class="label" for="agenda-promotion">Promotion</label>
			<div class="select is-fullwidth mb-4">
				<select id="agenda-promotion" bind:value={promotionId}
					><option value={null}>Aucune</option
					>{#each data.catalog.promotions as promotion (promotion.id)}<option value={promotion.id}
							>{promotion.name}</option
						>{/each}</select
				>
			</div>
			{#if !editing}<label class="label" for="agenda-year">Année scolaire obligatoire</label>
				<div class="select is-fullwidth mb-4">
					<select
						id="agenda-year"
						bind:value={schoolYear}
						onchange={() => (settings = defaultTimetableSettings(schoolYear))}
						required
						><option value={0} disabled>Choisir une année</option
						>{#each (data.catalog.common_years ?? []).filter((year) => year.school_year >= currentSchoolYear(data.catalog.today)) as year (year.school_year)}<option
								value={year.school_year}>{year.school_year}/{year.school_year + 1}</option
							>{/each}</select
					>
				</div>
				{#if !data.catalog.common_years?.length}<p class="notification is-warning is-light">
						Créez d’abord une année dans « Salles et années scolaires ».
					</p>{/if}
				<TimetableSettingsEditor bind:settings />
				<p class="help mt-4">
					Le calendrier sera créé avec la diffusion coupée. Horaires, pauses, séance et self seront
					figés.
				</p>{/if}
			<button class="button is-primary mt-5" disabled={busy || (!editing && !schoolYear)}
				>Enregistrer</button
			>
		</form></Modal
	>{/if}
{#if pending}<Modal
		title={pending.action === 'archive'
			? 'Archiver le calendrier'
			: pending.action === 'restore'
				? 'Réactiver l’archive'
				: 'Confirmer le changement'}
		{busy}
		onclose={() => (pending = null)}
	>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<p>Calendrier « {pending.agenda.name} ».</p>
		{#if pending.action === 'archive'}<p class="mt-3">
				La diffusion et les abonnements seront coupés. Le calendrier sera en lecture seule et ne
				participera plus aux emplois du temps et conflits des professeurs.
			</p>
		{:else if pending.action === 'restore'}<p class="mt-3">
				La diffusion restera coupée après réactivation.
			</p>
			<label class="checkbox mt-4"
				><input type="checkbox" bind:checked={detachPromotion} /> Réactiver sans promotion affectée (nécessaire
				si elle possède déjà un calendrier actif)</label
			>
		{:else if pending.action === 'toggle'}<p class="mt-3">
				{pending.agenda.is_paused
					? 'Les élèves affectés à cette promotion pourront récupérer leur lien dans /me et recevoir leurs séances par abonnement ICS.'
					: 'Les élèves ne recevront plus le lien ni les événements de ce calendrier. Les enseignants et khôlleurs conserveront leurs propres séances et abonnements.'}
			</p>
		{:else}<p class="mt-3">
				Les changements seront immédiatement appliqués. Changer la promotion retire l’accès aux
				anciens destinataires, donne accès aux nouveaux et recalcule les contrôles de groupes et de
				repas.
			</p>{/if}
		<div class="buttons mt-5">
			<button class="button is-primary" disabled={busy} onclick={confirm}>Confirmer</button><button
				class="button is-light"
				disabled={busy}
				onclick={() => (pending = null)}>Annuler</button
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
