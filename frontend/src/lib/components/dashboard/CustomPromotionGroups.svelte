<script lang="ts">
	import { untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { command, read } from '#lib/dashboard';
	import type { PromotionGroupsData } from '#lib/groups';
	import GroupMap, { type GroupMapNode } from './GroupMap.svelte';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	interface CustomGroup {
		id: number;
		name: string;
		revision: string | null;
		student_ids: number[];
		x: number;
		y: number;
	}
	let {
		promotionId,
		students,
		editable,
		rosterRevision,
		ondirty,
		onchanged
	}: {
		promotionId: number;
		students: PromotionGroupsData['students'];
		editable: boolean;
		rosterRevision: number;
		ondirty: (dirty: boolean) => void;
		onchanged: () => void;
	} = $props();
	let groups = $state<CustomGroup[]>([]);
	let live = $state(false);
	let loading = $state(true);
	let busy = $state(false);
	let stale = $state(false);
	let message = $state('');
	let success = $state('');
	let draft = $state<CustomGroup | null>(null);
	let nameOpen = $state(false);
	let name = $state('');
	let listView = $state(false);
	let selectedStudent = $state<number | null>(null);
	let confirmation = $state<'save' | 'delete' | null>(null);
	let deleting = $state<CustomGroup | null>(null);
	let sourcePosition = $state({ x: 20, y: 20 });
	const names = $derived(
		students.map((student) => ({
			id: student.id,
			name: `${student.first_name} ${student.last_name}`,
			archived: student.status === 'disabled'
		}))
	);
	const pupils = $derived(students.filter((student) => student.status !== 'disabled'));
	const nodes = $derived<GroupMapNode[]>([
		{
			number: 0,
			label: 'Classe entière',
			...sourcePosition,
			student_ids: students.map((student) => student.id)
		},
		...groups
			.filter((group) => group.id !== draft?.id)
			.map((group, index) => ({
				...group,
				number: group.id,
				label: group.name,
				x: group.x ?? 320 + (index % 3) * 300,
				y: group.y ?? Math.floor(index / 3) * 350 + 20
			})),
		...(draft ? [{ ...draft, number: draft.id || -1, label: draft.name }] : [])
	]);
	async function load(signal?: AbortSignal): Promise<void> {
		loading = true;
		message = '';
		try {
			const result = await read<{ groups: CustomGroup[]; live: boolean }>(
				'customPromotionGroups',
				{ id: promotionId },
				signal
			);
			if (!signal?.aborted) {
				groups = result.groups;
				live = result.live;
				stale = false;
			}
		} catch (cause) {
			if (!signal?.aborted) message = (cause as Error).message;
		} finally {
			if (!signal?.aborted) loading = false;
		}
	}
	$effect(() => {
		void promotionId;
		void rosterRevision;
		const controller = new AbortController();
		untrack(() => {
			if (draft) {
				stale = true;
				message = 'Les membres ont changé. Annulez puis rechargez les groupes.';
			} else void load(controller.signal);
		});
		return () => controller.abort();
	});
	$effect(() => {
		ondirty(draft !== null);
	});
	beforeNavigate((navigation) => {
		if (draft && !window.confirm('Quitter sans enregistrer le groupe ?')) navigation.cancel();
	});
	function beforeUnload(event: BeforeUnloadEvent): void {
		if (draft) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	function begin(group: CustomGroup | null): void {
		message = '';
		success = '';
		selectedStudent = null;
		draft = group
			? {
					...group,
					student_ids: group.student_ids.filter((id) => pupils.some((student) => student.id === id))
				}
			: {
					id: 0,
					name: name.trim(),
					revision: null,
					student_ids: [],
					x: 320 + (groups.length % 3) * 300,
					y: Math.floor(groups.length / 3) * 350 + 20
				};
		nameOpen = false;
	}
	function cancel(): void {
		draft = null;
		confirmation = null;
		selectedStudent = null;
		message = '';
		if (stale) void load();
	}
	function transfer(id: number, source: number | null, target: number): void {
		if (!draft || busy || stale || !pupils.some((student) => student.id === id)) return;
		if (target === 0 && source === (draft.id || -1))
			draft.student_ids = draft.student_ids.filter((student) => student !== id);
		else if (target === (draft.id || -1) && !draft.student_ids.includes(id))
			draft.student_ids = [...draft.student_ids, id];
	}
	function move(number: number, x: number, y: number): void {
		if (number === 0) sourcePosition = { x, y };
		else if (draft && number === (draft.id || -1)) {
			draft.x = x;
			draft.y = y;
		} else groups = groups.map((group) => (group.id === number ? { ...group, x, y } : group));
	}
	function arrange(): void {
		nodes.forEach((node, index) =>
			move(node.number, (index % 3) * 300 + 20, Math.floor(index / 3) * 350 + 20)
		);
	}
	async function save(confirmed = false): Promise<void> {
		if (!draft || !draft.student_ids.length || !draft.name.trim() || stale) return;
		if (draft.id && live && !confirmed) {
			confirmation = 'save';
			return;
		}
		busy = true;
		message = '';
		try {
			await command('saveCustomGroup', {
				id: promotionId,
				groupId: draft.id,
				data: {
					name: draft.name,
					student_ids: draft.student_ids,
					x: draft.x,
					y: draft.y,
					expected_revision: draft.revision,
					confirmed_live: confirmed
				}
			});
			draft = null;
			confirmation = null;
			selectedStudent = null;
			await load();
			success = 'Groupe enregistré.';
			onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function remove(): Promise<void> {
		if (!deleting) return;
		busy = true;
		message = '';
		try {
			await command('deleteCustomGroup', {
				id: promotionId,
				groupId: deleting.id,
				data: { expected_revision: deleting.revision, confirmed_live: true }
			});
			confirmation = null;
			deleting = null;
			await load();
			success = 'Groupe supprimé des choix proposés.';
			onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window onbeforeunload={beforeUnload} />
{#if message && !confirmation}<p role="alert" class="notification is-danger is-light">
		{message}
	</p>{/if}
{#if success}<p role="status" class="notification is-success is-light">{success}</p>{/if}
{#if loading}<p class="loading-state" role="status">Chargement des groupes…</p>{:else}
	<div class="group-toolbar">
		{#if draft}<div class="draft-name">
				<label class="label text-small" for="custom-group-name">Nom du groupe</label><input
					id="custom-group-name"
					class="input"
					maxlength="100"
					bind:value={draft.name}
					disabled={busy || confirmation !== null}
				/>
			</div>
			<div class="buttons mb-0">
				<button
					class="button is-primary"
					disabled={busy || stale || !draft.name.trim() || !draft.student_ids.length}
					onclick={() => save()}><Icon name="save" />Enregistrer</button
				><button class="button is-light" disabled={busy} onclick={cancel}>Annuler</button>
			</div>
		{:else if editable}<button
				class="button is-primary"
				disabled={busy || !pupils.length}
				onclick={() => {
					name = '';
					nameOpen = true;
				}}><Icon name="plus" />Créer un groupe</button
			>{/if}
		<div class="buttons mb-0">
			<button
				class="button is-small is-light"
				disabled={busy}
				onclick={() => (listView = !listView)}>{listView ? 'Vue bulles' : 'Vue liste'}</button
			><button class="button is-small is-light" disabled={busy} onclick={arrange}
				>Ranger les bulles</button
			>
		</div>
	</div>
	{#if draft}<p class="notification is-info is-light mt-4">
			Glissez les élèves de « Classe entière » vers « {draft.name} », ou sélectionnez un nom puis « Ajouter
			ici ». Pour retirer un élève, ramenez-le vers la classe. Minimum : un élève.
		</p>{/if}
	<GroupMap
		groups={nodes}
		students={names}
		editing={draft !== null && !stale}
		{busy}
		{listView}
		bind:selectedStudent
		editableGroups={draft ? [0, draft.id || -1] : []}
		copyMembers
		ontransfer={transfer}
		onmove={move}
	>
		{#snippet actions(node)}
			{#if node.number > 0 && editable && !draft}<div class="buttons mt-3 mb-0">
					<button
						class="button is-small is-light"
						disabled={busy}
						onclick={() => begin(groups.find((group) => group.id === node.number) ?? null)}
						><Icon name="edit" />Modifier</button
					>
					<button
						class="button is-small is-danger is-light"
						disabled={busy}
						onclick={() => {
							deleting = groups.find((group) => group.id === node.number) ?? null;
							confirmation = 'delete';
						}}><Icon name="remove" />Supprimer</button
					>
				</div>{/if}
		{/snippet}
	</GroupMap>
{/if}
{#if nameOpen}<Modal title="Créer un groupe personnalisé" onclose={() => (nameOpen = false)}>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				begin(null);
			}}
		>
			<label class="label" for="new-custom-name">Nom</label><input
				id="new-custom-name"
				class="input"
				bind:value={name}
				maxlength="100"
				required
			/><button class="button is-primary mt-4" disabled={!name.trim()}>Créer le bloc</button>
		</form>
	</Modal>{/if}
{#if confirmation}<Modal
		title={confirmation === 'delete' ? 'Supprimer le groupe' : 'Modifier le groupe diffusé'}
		{busy}
		onclose={() => {
			if (!busy) confirmation = null;
		}}
	>
		{#if confirmation === 'delete'}<p>
				Supprimer « {deleting?.name} » des groupes proposés ? Les séances déjà affectées à ce groupe conserveront
				leurs destinataires.
			</p>{:else}<p>
				Les séances de « {draft?.name} » seront immédiatement proposées aux {draft?.student_ids
					.length} élèves sélectionnés.
			</p>{/if}
		{#if live}<p class="notification is-warning is-light mt-3">
				<Icon name="info" />Un calendrier de cette promotion est diffusé en direct.
			</p>{/if}
		{#if message}<p role="alert" class="notification is-danger is-light mt-3">{message}</p>{/if}
		<div class="buttons mt-4">
			<button
				class="button"
				class:is-danger={confirmation === 'delete'}
				class:is-primary={confirmation === 'save'}
				disabled={busy}
				onclick={() => (confirmation === 'delete' ? remove() : save(true))}
				>Confirmer {confirmation === 'delete' ? 'la suppression' : 'la modification'}</button
			><button class="button is-light" disabled={busy} onclick={() => (confirmation = null)}
				>Annuler</button
			>
		</div>
	</Modal>{/if}

<style>
	.group-toolbar {
		display: flex;
		align-items: end;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 1rem;
	}
	.draft-name {
		flex: 1;
		min-width: 12rem;
	}
	button {
		gap: 0.4rem;
	}
</style>
