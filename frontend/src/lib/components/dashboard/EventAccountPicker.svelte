<script lang="ts">
	import { onMount } from 'svelte';
	import { read, roleLabels, statusLabels } from '#lib/dashboard';
	import type { DirectoryUser, Page } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import AccountIdentity from '../AccountIdentity.svelte';
	let {
		selected,
		onclose,
		onapply
	}: {
		selected: DirectoryUser | null;
		onclose: () => void;
		onapply: (user: DirectoryUser | null) => void;
	} = $props();
	let choice = $state<DirectoryUser | null>(null);
	let query = $state('');
	let role = $state('');
	let users = $state<DirectoryUser[]>([]);
	let ready = $state(false);
	let loading = $state(true);
	let error = $state('');
	onMount(() => {
		choice = selected;
		ready = true;
	});
	$effect(() => {
		const q = query.trim(),
			r = role;
		if (!ready) return;
		const controller = new AbortController();
		loading = true;
		const timer = setTimeout(
			async () => {
				error = '';
				try {
					const params = { q: q || undefined, role: r || undefined, limit: 20 };
					const result =
						q.length >= 2
							? await read<DirectoryUser[]>('search', params, controller.signal)
							: q.length === 1
								? []
								: (await read<Page<DirectoryUser>>('users', params, controller.signal)).items;
					if (!controller.signal.aborted) users = result;
				} catch (cause) {
					if (!controller.signal.aborted) error = (cause as Error).message;
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
</script>

<Modal
	title="Filtrer par compte"
	description="Recherchez un compte actif ou archivé, auteur ou cible des événements."
	{onclose}
>
	<div class="account-picker-toolbar">
		<div class="search-field">
			<Icon name="search" size={16} />
			<input
				class="input"
				aria-label="Rechercher un compte"
				placeholder="Nom, prénom ou identifiant…"
				bind:value={query}
			/>
		</div>
		<div class="select">
			<select aria-label="Rôle du compte" bind:value={role}
				><option value="">Tous les rôles</option
				>{#each Object.entries(roleLabels) as [code, label] (code)}<option value={code}
						>{label}</option
					>{/each}</select
			>
		</div>
	</div>
	{#if choice}<p class="help">
			Compte sélectionné : {choice.first_name}
			{choice.last_name} · {statusLabels[choice.status]}
		</p>{/if}
	{#if error}<p class="notification is-danger is-light" role="alert">{error}</p>{/if}
	<div class="member-picker" aria-busy={loading}>
		{#if loading}<p class="loading-state" role="status">Recherche…</p>{:else if !error}
			{#each users as user (user.id)}<label
					class="member-choice"
					class:selected={choice?.id === user.id}
					><input
						type="radio"
						name="event-account"
						checked={choice?.id === user.id}
						onchange={() => (choice = user)}
					/><AccountIdentity {user} /></label
				>{:else}<p class="empty-state">
					{query.trim().length === 1
						? 'Saisissez au moins deux caractères.'
						: 'Aucun compte trouvé.'}
				</p>{/each}
		{/if}
	</div>
	<div class="dialog-actions">
		{#if choice}<button class="button is-text" onclick={() => (choice = null)}
				>Effacer la sélection</button
			>{/if}
		<button class="button is-light" onclick={onclose}>Annuler</button><button
			class="button is-primary"
			onclick={() => onapply(choice)}>Appliquer</button
		>
	</div>
</Modal>
