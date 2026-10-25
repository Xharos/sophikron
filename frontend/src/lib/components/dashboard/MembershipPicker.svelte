<script lang="ts">
	import { onMount } from 'svelte';
	import { command, read, statusLabels } from '#lib/dashboard';
	import type { DirectoryUser, Page, Promotion } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	let {
		promotion,
		onclose,
		onsaved
	}: { promotion: Promotion; onclose: () => void; onsaved: () => void } = $props();
	let query = $state('');
	let role = $state('user');
	let users = $state<DirectoryUser[]>([]);
	let selected = $state<number[]>([]);
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let ready = $state(false);
	onMount(() => {
		ready = true;
	});
	$effect(() => {
		const q = query;
		const r = role;
		if (!ready) return;
		const controller = new AbortController();
		const timer = setTimeout(
			async () => {
				loading = true;
				message = '';
				try {
					if (q.trim().length >= 2)
						users = await read<DirectoryUser[]>(
							'search',
							{ q, role: r, limit: 20 },
							controller.signal
						);
					else if (!q.trim())
						users = (
							await read<Page<DirectoryUser>>('users', { role: r, limit: 20 }, controller.signal)
						).items;
					else users = [];
				} catch (cause) {
					if (!controller.signal.aborted) message = (cause as Error).message;
				} finally {
					if (!controller.signal.aborted) loading = false;
				}
			},
			q ? 220 : 0
		);
		return () => {
			controller.abort();
			clearTimeout(timer);
		};
	});
	async function save(): Promise<void> {
		busy = true;
		message = '';
		try {
			await command('addMembers', { id: promotion.id, data: { user_ids: selected } });
			onsaved();
			onclose();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal
	title={`Ajouter à ${promotion.identifier} ${promotion.year}`}
	description="Sélectionnez les comptes à affecter à cette promotion."
	{busy}
	{onclose}
>
	<div class="list-toolbar">
		<div class="search-field">
			<Icon name="search" /><input
				class="input"
				aria-label="Rechercher des comptes à ajouter"
				placeholder="Nom, prénom ou identifiant…"
				bind:value={query}
			/>
		</div>
		<div class="select">
			<select aria-label="Type de compte" bind:value={role}
				><option value="user">Élèves</option><option value="teacher">Professeurs</option><option
					value="admin">Administrateurs</option
				><option value="">Tous les comptes</option></select
			>
		</div>
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<div class="member-picker" aria-busy={loading}>
		{#if loading}<p class="loading-state">Recherche…</p>{:else}{#each users as user (user.id)}<label
					class="member-choice"
					><input type="checkbox" value={user.id} bind:group={selected} disabled={busy} />
					<span
						><strong>{user.first_name} {user.last_name}</strong><span class="muted text-small block"
							>@{user.username} · {statusLabels[user.status]}</span
						></span
					></label
				>{/each}
			{#if users.length === 0}<p class="empty-state">Aucun compte trouvé.</p>{/if}{/if}
	</div>
	<p class="help mt-3">
		{selected.length} compte(s) sélectionné(s). Les affectations existantes seront conservées.
	</p>
	<div class="dialog-actions">
		<button class="button is-light" disabled={busy} onclick={onclose}>Annuler</button><button
			class="button is-primary"
			class:is-loading={busy}
			disabled={busy || selected.length === 0}
			onclick={save}><Icon name="plus" />Ajouter la sélection</button
		>
	</div>
</Modal>
