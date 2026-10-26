<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { read, statusLabels } from '#lib/dashboard';
	import RoleBadges from '../RoleBadges.svelte';
	import GroupTags from '../GroupTags.svelte';
	import type { DirectoryUser, Page } from '#lib/types';
	import Icon from '../Icon.svelte';
	import Pagination from '../Pagination.svelte';
	import AccountCreator from './AccountCreator.svelte';
	import AccountProfile from './AccountProfile.svelte';
	let {
		administrator,
		currentUserId,
		promotionId,
		initialCreate = false,
		onchanged = () => {}
	}: {
		administrator: boolean;
		currentUserId: number;
		promotionId?: number;
		initialCreate?: boolean;
		onchanged?: () => void;
	} = $props();
	let query = $state('');
	let role = $state('');
	let status = $state('');
	let offset = $state(0);
	let users = $state<DirectoryUser[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let message = $state('');
	let create = $state(untrack(() => initialCreate));
	let profile = $state<number | null>(null);
	let refresh = $state(0);
	let ready = $state(false);
	let controller: AbortController | undefined;
	onMount(() => {
		ready = true;
		return () => controller?.abort();
	});
	$effect(() => {
		const q = query;
		const r = role;
		const s = status;
		const page = offset;
		const p = promotionId;
		void refresh;
		if (!ready) return;
		const timer = setTimeout(
			() => {
				void load(q, r, s, page, p);
			},
			q ? 220 : 0
		);
		return () => {
			clearTimeout(timer);
			controller?.abort();
		};
	});
	async function load(
		q: string,
		r: string,
		s: string,
		page: number,
		promotion?: number
	): Promise<void> {
		controller?.abort();
		const request = new AbortController();
		controller = request;
		loading = true;
		message = '';
		if (q.trim().length === 1) {
			users = [];
			total = 0;
			loading = false;
			return;
		}
		try {
			const params = {
				q,
				role: administrator ? r : undefined,
				status: administrator ? s : undefined,
				promotion_id: promotion,
				offset: page,
				limit: 20
			};
			if (q.trim().length >= 2) {
				users = await read<DirectoryUser[]>('search', params, request.signal);
				total = users.length;
			} else {
				const result = await read<Page<DirectoryUser>>('users', params, request.signal);
				users = result.items;
				total = result.total;
			}
		} catch (cause) {
			if (!request.signal.aborted) message = (cause as Error).message;
		} finally {
			if (!request.signal.aborted) loading = false;
		}
	}
	function changed(): void {
		refresh += 1;
		onchanged();
	}
</script>

<section class="workspace-panel">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">{promotionId ? 'Membres de la promotion' : 'Annuaire'}</p>
			<h2 class="title is-4 mb-2">{administrator ? 'Comptes' : 'Élèves'}</h2>
			<p class="muted text-small">
				{administrator
					? 'Retrouvez un compte et gérez ses accès.'
					: 'Vos élèves, y compris les comptes archivés, en lecture seule.'}
			</p>
		</div>
		{#if administrator}<button class="button is-primary" onclick={() => (create = true)}
				><Icon name="plus" />Créer un compte</button
			>{/if}
	</div>
	<div class="list-toolbar">
		<div class="search-field">
			<Icon name="search" /><input
				class="input"
				aria-label="Rechercher un compte"
				placeholder="Nom, prénom ou identifiant…"
				bind:value={query}
				oninput={() => (offset = 0)}
			/>
		</div>
		{#if administrator}<div class="select">
				<select aria-label="Filtrer par rôle" bind:value={role} onchange={() => (offset = 0)}
					><option value="">Tous les rôles</option><option value="user">Élèves</option><option
						value={promotionId ? 'teaching' : 'teacher'}>Professeurs</option
					>{#if !promotionId}<option value="kholleur">Khôlleurs</option><option value="admin"
							>Administrateurs</option
						>{/if}</select
				>
			</div>
			<div class="select">
				<select aria-label="Filtrer par statut" bind:value={status} onchange={() => (offset = 0)}
					><option value="">Tous les états</option><option value="active">Actifs</option><option
						value="pending_activation">À activer</option
					><option value="disabled">Archivés</option></select
				>
			</div>{/if}
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">
			{message}<button class="button is-small ml-3" onclick={changed}>Réessayer</button>
		</p>{/if}
	<div class="account-list" aria-busy={loading}>
		{#if loading}<p class="loading-state" role="status">Recherche des comptes…</p>
		{:else if users.length === 0}<div class="empty-state">
				<Icon name="accounts" size={30} />
				<p>
					{query.trim().length === 1
						? 'Saisissez au moins deux caractères.'
						: 'Aucun compte trouvé.'}
				</p>
			</div>
		{:else}{#each users as user (user.id)}<button
					class="account-row"
					onclick={() => (profile = user.id)}
				>
					<span class="avatar">{user.first_name?.slice(0, 1)}{user.last_name?.slice(0, 1)}</span
					><span class="account-identity"
						><strong>{user.first_name} {user.last_name}</strong><span class="muted text-small"
							>@{user.username}</span
						>
						{#if promotionId}<GroupTags assignments={user.group_assignments} {promotionId} />{/if}
					</span>
					<span class="account-role"><RoleBadges roles={user.roles ?? []} /></span>
					<span
						class="account-status"
						class:archived={user.status === 'disabled'}
						class:pending={user.status === 'pending_activation'}>{statusLabels[user.status]}</span
					><Icon name="next" size={13} /></button
				>{/each}{/if}
	</div>
	{#if !query.trim()}<Pagination
			{offset}
			limit={20}
			{total}
			busy={loading}
			onchange={(value) => (offset = value)}
		/>{:else if total > 0}<p class="help mt-3">
			{total === 1 ? 'La' : 'Les'}
			{total} meilleure{total === 1 ? '' : 's'} correspondance{total === 1 ? '' : 's'}
			{total === 1 ? 'est affichée' : 'sont affichées'}.
		</p>{/if}
</section>
{#if create}<AccountCreator
		{promotionId}
		onclose={() => (create = false)}
		oncreated={changed}
	/>{/if}
{#if profile !== null}{#key profile}<AccountProfile
			userId={profile}
			{administrator}
			{currentUserId}
			onclose={() => (profile = null)}
			onchanged={changed}
		/>{/key}{/if}
