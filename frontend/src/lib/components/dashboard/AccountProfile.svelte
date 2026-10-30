<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { activePromotions, command, formatDate, read, statusLabels } from '#lib/dashboard';
	import { canJoinPromotion } from '#lib/roles';
	import type { AdminAccount, DirectoryUser, Page, Promotion } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import RoleBadges from '../RoleBadges.svelte';
	import PromotionTag from '../PromotionTag.svelte';
	import GroupTags from '../GroupTags.svelte';
	import AccountAccess from './AccountAccess.svelte';
	let {
		userId,
		administrator,
		currentUserId,
		onclose,
		onchanged
	}: {
		userId: number;
		administrator: boolean;
		currentUserId: number;
		onclose: () => void;
		onchanged: () => void;
	} = $props();
	let account = $state<AdminAccount | DirectoryUser | null>(null);
	let memberships = $state<Promotion[]>([]);
	let choices = $state<Promotion[]>([]);
	let selected = $state(0);
	let busy = $state(false);
	let loading = $state(true);
	let message = $state('');
	const details = $derived(administrator && account ? (account as AdminAccount) : null);
	const available = $derived(
		choices.filter((item) => !memberships.some((member) => member.id === item.id))
	);
	const invitationLabels: Record<string, string> = {
		none: 'Aucune invitation',
		pending: 'Invitation en cours',
		expired: 'Invitation expirée',
		used: 'Invitation utilisée',
		revoked: 'Invitation révoquée'
	};
	async function load(): Promise<void> {
		loading = true;
		try {
			account = await read<AdminAccount | DirectoryUser>('user', { id: userId });
			if (administrator) {
				const [assigned, options] = await Promise.all([
					read<Page<Promotion>>('userPromotions', { id: userId, limit: 100 }),
					activePromotions()
				]);
				memberships = assigned.items;
				choices = options;
			} else memberships = (account as DirectoryUser).promotions ?? [];
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	}
	onMount(() => {
		void load();
	});
	async function membership(promotionId: number, add: boolean): Promise<void> {
		busy = true;
		message = '';
		try {
			await command('membership', { userId, promotionId, add });
			selected = 0;
			await load();
			onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<Modal
	title="Fiche du compte"
	description={administrator
		? 'Identité, promotions et accès au compte.'
		: 'Consultation des élèves de vos promotions.'}
	drawer
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if loading && !account}<div class="loading-state" role="status">Chargement du profil…</div>{/if}
	{#if account}
		<a class="button is-primary is-fullwidth mb-5" href={resolve(`/dashboard/user?id=${userId}`)}
			><Icon name="profile" />Voir la fiche complète</a
		>
		<div class="profile-hero" class:archived-account={account.status === 'disabled'}>
			<div class="avatar large">
				{account.first_name?.slice(0, 1)}{account.last_name?.slice(0, 1)}
			</div>
			<div>
				<h3 class="title is-4 mb-2">{account.first_name} {account.last_name}</h3>
				<p class="muted">@{account.username}</p>
				<span
					class="account-status mt-2"
					class:archived={account.status === 'disabled'}
					class:pending={account.status === 'pending_activation'}
					>{statusLabels[account.status]}</span
				>
			</div>
		</div>
		{#if details}<dl class="profile-details mt-5">
				<dt>Email</dt>
				<dd>{details.email}</dd>
				<dt>Rôles</dt>
				<dd><RoleBadges roles={details.roles} /></dd>
				<dt>Création</dt>
				<dd>{formatDate(details.created_at)}</dd>
				<dt>Dernière connexion</dt>
				<dd>{formatDate(details.last_login_at)}</dd>
				<dt>Connexions réussies</dt>
				<dd>{details.login_count}</dd>
				<dt>Mot de passe modifié</dt>
				<dd>{formatDate(details.password_changed_at)}</dd>
				<dt>Invitation</dt>
				<dd>
					{invitationLabels[details.invitation.status]}{#if details.invitation.expires_at}<span
							class="muted text-small block"
							>Expiration : {formatDate(details.invitation.expires_at)}</span
						>{/if}
				</dd>
				{#if details.archived_at}<dt>Archivage</dt>
					<dd>{formatDate(details.archived_at)}</dd>{/if}
			</dl>{/if}
		<section class="profile-section">
			<h3 class="title is-5">
				Promotions {#if !administrator}<span class="muted text-small">partagées avec vous</span
					>{/if}
			</h3>
			{#each memberships as promotion (promotion.id)}<div
					class="membership-row"
					class:archived-account={account.status === 'disabled'}
				>
					<div class="is-flex is-flex-wrap-wrap is-align-items-center" style="gap: 0.5rem">
						<PromotionTag {promotion} />
						<GroupTags assignments={account.group_assignments} promotionId={promotion.id} />
					</div>
					{#if administrator}<button
							class="icon-button"
							title="Retirer cette affectation"
							aria-label={`Retirer ${promotion.identifier} ${promotion.year}`}
							disabled={busy}
							onclick={() => membership(promotion.id, false)}><Icon name="close" /></button
						>{/if}
				</div>{/each}
			{#if memberships.length === 0}<p class="muted">Aucune promotion affectée.</p>{/if}
			{#if administrator && account.roles && canJoinPromotion(account.roles) && available.length > 0}<div
					class="inline-form mt-4"
				>
					<div class="select is-fullwidth">
						<select aria-label="Promotion à ajouter" bind:value={selected} disabled={busy}>
							<option value={0}>Ajouter une promotion…</option
							>{#each available as promotion (promotion.id)}<option value={promotion.id}
									>{promotion.identifier} {promotion.year}</option
								>{/each}</select
						>
					</div>
					<button
						class="button is-light"
						disabled={busy || !selected}
						onclick={() => membership(selected, true)}><Icon name="plus" />Ajouter</button
					>
				</div>{/if}
		</section>
		{#if administrator}<AccountAccess
				{userId}
				status={account.status}
				{currentUserId}
				onchanged={async () => {
					await load();
					onchanged();
				}}
			/>{:else}<section class="profile-section">
				<h3 class="title is-5">Activité pédagogique</h3>
				<p class="muted">Aucune activité pédagogique disponible pour le moment.</p>
			</section>{/if}
	{/if}
</Modal>
