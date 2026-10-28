<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { invalidateAll } from '$app/navigation';
	import { timetableCommand } from '#lib/timetableClient';
	import { defaultTimetableSettings, type TimetableSettings } from '#lib/timetable';
	import TimetableSettingsEditor from '#lib/components/TimetableSettings.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let tab = $state<'year' | 'rooms'>('year');
	let year = $state(
		untrack(() => data.configuration.years[0]?.school_year ?? new Date().getFullYear())
	);
	let settings = $state<TimetableSettings>(untrack(() => defaultTimetableSettings(year)));
	let revision = $state<string | null>(null);
	let busy = $state(false);
	let message = $state('');
	let notice = $state('');
	let room = $state<{ id: number; name: string; revision: string } | null>(null);
	let roomOpen = $state(false);
	let roomName = $state('');
	let deleting = $state(false);
	const existing = $derived(data.configuration.years.find((item) => item.school_year === year));
	$effect(() => {
		const value = existing;
		settings = structuredClone(value?.settings ?? defaultTimetableSettings(year));
		revision = value?.revision ?? null;
	});
	async function saveYear(): Promise<void> {
		busy = true;
		message = '';
		notice = '';
		try {
			await timetableCommand('configuration', 'PUT', { expected_revision: revision, settings });
			year = Number(settings.start.slice(0, 4));
			await invalidateAll();
			notice = 'Réglages communs enregistrés dans les brouillons.';
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
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
	><title>Réglages des calendriers — {data.establishmentName}</title><meta
		name="description"
		content="Réglages communs des salles et de l’année scolaire."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container common-settings">
	<a class="back-link" href={resolve('/timetable')}>← Agendas</a>
	<h1 class="title is-3 mt-4">Réglages communs</h1>
	<div class="tabs mt-5">
		<ul>
			<li class:is-active={tab === 'year'}>
				<button
					onclick={() => {
						tab = 'year';
						message = '';
					}}>Année scolaire</button
				>
			</li>
			<li class:is-active={tab === 'rooms'}>
				<button
					onclick={() => {
						tab = 'rooms';
						message = '';
					}}>Salles</button
				>
			</li>
		</ul>
	</div>
	{#if message && !roomOpen}<p class="notification is-danger is-light" role="alert">
			{message}
		</p>{/if}
	{#if notice}<p class="notification is-success is-light" role="status">{notice}</p>{/if}
	{#if tab === 'year'}<div class="workspace-panel">
			<div class="year-choice">
				<label class="label" for="school-year">Année de rentrée</label><input
					id="school-year"
					class="input"
					type="number"
					min="1900"
					max="9998"
					bind:value={year}
				/>
				{#if data.configuration.years.length}<div class="buttons mt-3">
						{#each data.configuration.years as item (item.school_year)}<button
								class="button is-small is-light"
								onclick={() => (year = item.school_year)}
								>{item.school_year}–{item.school_year + 1}</button
							>{/each}
					</div>{/if}
			</div>
			{#if existing && !existing.settings && existing.alternatives.length}<div
					class="notification is-warning is-light"
				>
					<p>
						Les agendas existants ont des réglages différents. Choisissez une base avant
						d’enregistrer les réglages communs.
					</p>
					<div class="buttons mt-3">
						{#each existing.alternatives as alternative, index (index)}<button
								class="button is-small"
								onclick={() => (settings = structuredClone(alternative.settings))}
								>Reprendre « {alternative.name} »</button
							>{/each}
					</div>
				</div>{/if}
			<form
				onsubmit={(event) => {
					event.preventDefault();
					void saveYear();
				}}
			>
				<TimetableSettingsEditor bind:settings />
				<div class="settings-footer">
					<p class="help">
						Ces réglages s’appliquent aux brouillons de tous les agendas. Les publications restent
						inchangées jusqu’à leur prochaine publication.
					</p>
					<button class="button is-primary" disabled={busy}>Enregistrer</button>
				</div>
			</form>
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

<style>
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
	.year-choice {
		padding-bottom: 1.5rem;
		margin-bottom: 1.5rem;
		border-bottom: var(--border-thin);
	}
	.year-choice input {
		width: 130px;
	}
	.settings-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin-top: 2rem;
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
