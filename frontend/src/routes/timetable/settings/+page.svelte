<script lang="ts">
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import { timetableCommand } from '#lib/timetableClient';
	import Modal from '#lib/components/Modal.svelte';
	import { currentSchoolYear, type CommonTimetableYear } from '#lib/timetable';
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let tab = $state<'year' | 'rooms' | 'archive'>('year');
	let year = $state(0);
	let enablingArchive = $state(false);
	const currentYear = $derived(currentSchoolYear(data.configuration.today));
	$effect(() => {
		if (!year) year = currentYear;
	});
	async function savePreferences(enabled: boolean): Promise<void> {
		busy = true;
		message = '';
		try {
			await timetableCommand('preferences', 'PUT', {
				auto_archive: enabled,
				expected_revision: data.configuration.preferences.revision
			});
			enablingArchive = false;
			await invalidateAll();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	let busy = $state(false);
	let message = $state('');
	let room = $state<{ id: number; name: string; revision: string } | null>(null);
	let roomOpen = $state(false);
	let roomName = $state('');
	let deleting = $state(false);
	let deletingYear = $state<CommonTimetableYear | null>(null);
	async function saveYear(): Promise<void> {
		busy = true;
		message = '';
		try {
			await timetableCommand('school-years', 'POST', { school_year: year });
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Création impossible.';
		} finally {
			busy = false;
		}
	}
	async function removeYear(): Promise<void> {
		if (!deletingYear) return;
		busy = true;
		message = '';
		try {
			await timetableCommand('school-years/' + deletingYear.school_year, 'DELETE', {
				expected_revision: deletingYear.revision
			});
			deletingYear = null;
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Suppression impossible.';
		} finally {
			busy = false;
		}
	}
	async function saveRoom(): Promise<void> {
		busy = true;
		message = '';
		try {
			await timetableCommand(
				room ? `rooms/${room.id}` : 'rooms',
				deleting ? 'DELETE' : room ? 'PUT' : 'POST',
				deleting
					? { expected_revision: room?.revision }
					: { name: roomName, expected_revision: room?.revision ?? null }
			);
			roomOpen = false;
			await invalidateAll();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	function editRoom(value: typeof room, remove = false): void {
		room = value;
		roomName = value?.name ?? '';
		deleting = remove;
		roomOpen = true;
		message = '';
	}
</script>

<svelte:head
	><title>Salles et années scolaires — {data.establishmentName}</title><meta
		name="description"
		content="Catalogue des salles et des années scolaires."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container common-settings">
	<a class="back-link" href={resolve('/timetable')}>← Agendas</a>
	<h1 class="title is-3 mt-4">Salles et années scolaires</h1>
	<div class="tabs mt-5">
		<ul>
			<li class:is-active={tab === 'archive'}>
				<button onclick={() => (tab = 'archive')}>Archivage automatique</button>
			</li>
			<li class:is-active={tab === 'year'}>
				<button onclick={() => (tab = 'year')}>Années scolaires</button>
			</li>
			<li class:is-active={tab === 'rooms'}>
				<button onclick={() => (tab = 'rooms')}>Salles</button>
			</li>
		</ul>
	</div>
	{#if message && !roomOpen}<p class="notification is-danger is-light" role="alert">
			{message}
		</p>{/if}
	{#if tab === 'archive'}<div class="workspace-panel">
			<label class="archive-switch"
				><input
					type="checkbox"
					role="switch"
					checked={data.configuration.preferences.auto_archive}
					disabled={busy}
					onchange={(event) => {
						if (event.currentTarget.checked) {
							event.currentTarget.checked = false;
							enablingArchive = true;
						} else void savePreferences(false);
					}}
				/><span>Archiver automatiquement les calendriers des années scolaires passées</span></label
			>
			<p class="help mt-3">
				Au 1er septembre, la diffusion est coupée et les calendriers de l’année précédente
				deviennent des archives en lecture seule. Les administrateurs peuvent les consulter et les
				réactiver.
			</p>
		</div>{:else if tab === 'year'}<div class="workspace-panel">
			<form
				onsubmit={(event) => {
					event.preventDefault();
					void saveYear();
				}}
			>
				<label class="label" for="school-year">Année de rentrée</label>
				<div class="field has-addons">
					<div class="control">
						<input
							id="school-year"
							class="input"
							type="number"
							min={currentYear}
							max="9998"
							step="1"
							required
							bind:value={year}
						/>
					</div>
					<div class="control">
						<button class="button is-primary" disabled={busy}>Créer {year}/{year + 1}</button>
					</div>
				</div>
			</form>
			<p class="help mb-4">
				Une année utilisée par un calendrier ou des disponibilités ne peut plus être supprimée.
			</p>
			{#each data.configuration.years as item (item.school_year)}<div class="room-row">
					<strong>{item.school_year}/{item.school_year + 1}</strong>{#if item.used}<span class="tag"
							>Utilisée · immuable</span
						>{:else}<button
							class="button is-small is-light"
							disabled={busy}
							onclick={() => (deletingYear = item)}>Supprimer</button
						>{/if}
				</div>{/each}
		</div>
	{:else}<div class="workspace-panel">
			<div class="room-heading">
				<h2 class="title is-5 mb-0">Salles de l’établissement</h2>
				<button class="button is-primary" onclick={() => editRoom(null)}>Ajouter une salle</button>
			</div>
			{#each data.configuration.rooms as item (item.id)}<div class="room-row">
					<strong>{item.name}</strong>
					<div class="buttons mb-0">
						<button class="button is-small is-light" onclick={() => editRoom(item)}>Modifier</button
						><button class="button is-small is-light" onclick={() => editRoom(item, true)}
							>Supprimer</button
						>
					</div>
				</div>{/each}
			{#if !data.configuration.rooms.length}<p class="muted mt-5">Aucune salle enregistrée.</p>{/if}
		</div>{/if}
</section>
{#if enablingArchive}<Modal
		title="Activer l’archivage automatique"
		onclose={() => (enablingArchive = false)}
	>
		<p>
			<Icon name="archive" /> Les calendriers des années antérieures à {currentYear}/{currentYear +
				1} seront archivés et leur diffusion coupée immédiatement.
		</p>
		<div class="buttons mt-4">
			<button class="button is-primary" disabled={busy} onclick={() => savePreferences(true)}
				>Activer et appliquer</button
			><button class="button is-light" disabled={busy} onclick={() => (enablingArchive = false)}
				>Annuler</button
			>
		</div>
	</Modal>{/if}
{#if roomOpen}<Modal
		title={deleting ? 'Supprimer la salle' : room ? 'Modifier la salle' : 'Ajouter une salle'}
		{busy}
		onclose={() => (roomOpen = false)}
	>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void saveRoom();
			}}
		>
			{#if deleting}<p>
					Retirer « {room?.name} » du catalogue ? Les séances existantes conserveront leur salle.
				</p>{:else}<label class="label" for="room-name">Nom de la salle</label><input
					class="input"
					id="room-name"
					bind:value={roomName}
					required
					maxlength="80"
				/>{/if}<button
				class="button mt-5"
				class:is-danger={deleting}
				class:is-primary={!deleting}
				disabled={busy}>{deleting ? 'Supprimer la salle' : 'Enregistrer'}</button
			>
		</form>
	</Modal>{/if}

{#if deletingYear}<Modal
		title="Supprimer l’année inutilisée"
		{busy}
		onclose={() => (deletingYear = null)}
		><p>Supprimer {deletingYear.school_year}/{deletingYear.school_year + 1} ?</p>
		<button class="button is-danger mt-5" disabled={busy} onclick={removeYear}>Confirmer</button
		></Modal
	>{/if}

<style>
	.archive-switch {
		display: flex;
		gap: 0.75rem;
		align-items: center;
		cursor: pointer;
	}
	.archive-switch input {
		appearance: none;
		width: 2.7rem;
		height: 1.5rem;
		border-radius: 1rem;
		background: var(--bulma-grey-light);
		position: relative;
		flex-shrink: 0;
	}
	.archive-switch input::after {
		content: '';
		position: absolute;
		width: 1.1rem;
		height: 1.1rem;
		border-radius: 50%;
		background: white;
		left: 0.2rem;
		top: 0.2rem;
		transition: transform 0.15s;
	}
	.archive-switch input:checked {
		background: var(--bulma-primary);
	}
	.archive-switch input:checked::after {
		transform: translateX(1.2rem);
	}
	.archive-switch input:focus-visible {
		outline: 2px solid var(--bulma-primary);
		outline-offset: 3px;
	}
	.common-settings {
		max-width: 850px;
	}
	.back-link {
		color: var(--color-muted);
		font-size: 0.9rem;
	}
	.tabs button {
		border: 0;
		background: none;
		color: inherit;
		padding: 0.8rem 1.2rem;
		cursor: pointer;
	}
	.tabs li.is-active button {
		color: var(--color-primary);
		border-bottom: 2px solid;
	}
	.room-heading,
	.room-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}
	.room-heading {
		margin-bottom: 1.5rem;
	}
	.room-row {
		padding: 1rem 0;
		border-top: var(--border-thin);
	}
</style>
