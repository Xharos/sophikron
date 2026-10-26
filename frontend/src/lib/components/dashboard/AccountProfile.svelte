<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { activePromotions, command, formatDate, read, statusLabels } from '#lib/dashboard';
	import { canJoinPromotion } from '#lib/roles';
	import type { AccessInvitation, AdminAccount, DirectoryUser, Page, Promotion } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import RoleBadges from '../RoleBadges.svelte';
	import PromotionTag from '../PromotionTag.svelte';
	import GroupTags from '../GroupTags.svelte';
	import InvitationResult from '../InvitationResult.svelte';
	import type { CourseImpact } from '#lib/site';
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
	let invitation = $state<AccessInvitation | null>(null);
	let confirmation = $state<'archive' | 'invite' | null>(null);
	let impacts = $state<CourseImpact[]>([]);
	async function prepareArchive(): Promise<void> {
		busy = true;
		message = '';
		try {
			impacts = await read<CourseImpact[]>('courseImpact', { id: userId });
			confirmation = 'archive';
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
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
	async function perform(): Promise<void> {
		if (!account || !confirmation) return;
		busy = true;
		message = '';
		try {
			if (confirmation === 'archive') {
				await command('archiveAccount', {
					id: userId,
					data: { archived: account.status !== 'disabled', acknowledge_course_impact: true }
				});
				invitation = null;
				onchanged();
			} else invitation = await command<AccessInvitation>('invitation', { id: userId });
			confirmation = null;
			await load();
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
		{#if administrator}<section class="profile-section">
				<h3 class="title is-5">Accès au compte</h3>
				<div class="profile-buttons">
					<button
						class="button is-light"
						disabled={busy || account.status === 'disabled'}
						onclick={() => (confirmation = 'invite')}
						><Icon name="email" />{account.status === 'pending_activation'
							? 'Nouvelle invitation'
							: 'Réinitialiser le mot de passe'}</button
					>
					<button
						class="button"
						class:is-danger={account.status !== 'disabled'}
						class:is-light={account.status !== 'disabled'}
						disabled={busy || currentUserId === userId}
						onclick={prepareArchive}
						><Icon
							name={account.status === 'disabled' ? 'restore' : 'archive'}
						/>{account.status === 'disabled' ? 'Réactiver le compte' : 'Archiver le compte'}</button
					>
				</div>
				{#if currentUserId === userId}<p class="help mt-2">
						Votre propre compte ne peut pas être archivé.
					</p>{/if}
				{#if confirmation}<div
						class="confirmation-panel mt-4"
						role="group"
						aria-label="Confirmation de l’action"
					>
						<p>
							{confirmation === 'invite'
								? 'Une nouvelle invitation sera envoyée par email si configuré, sinon un lien sera affiché. Les anciens liens ne fonctionneront plus.'
								: account.status === 'disabled'
									? 'Ce compte pourra à nouveau être utilisé. Les anciens liens et sessions resteront invalides.'
									: 'Ce compte ne pourra plus se connecter et ses sessions seront fermées. Ses informations seront conservées.'}
						</p>
						<div class="buttons mt-3">
							{#if confirmation === 'archive' && account.status !== 'disabled' && impacts.length}<div
									class="notification is-warning is-light"
									role="alert"
								>
									<p>
										<strong>Ce compte est associé à {impacts.length} cours.</strong> L’archivage supprimera
										ses matières affectées et ses collaborations, et révoquera tous ses accès.
									</p>
									<ul>
										{#each impacts as course (course.id)}<li>{course.title}</li>{/each}
									</ul>
									<p>
										Réaffectez si nécessaire le responsable depuis les pages de cours. La
										réactivation ne rétablira pas automatiquement ces affectations.
									</p>
								</div>{/if}
							<button
								class="button is-primary"
								class:is-loading={busy}
								disabled={busy}
								onclick={perform}>Confirmer</button
							><button class="button is-light" disabled={busy} onclick={() => (confirmation = null)}
								>Annuler</button
							>
						</div>
					</div>{/if}
				{#if invitation}<InvitationResult {invitation} />{/if}
			</section>{:else}<section class="profile-section">
				<h3 class="title is-5">Activité pédagogique</h3>
				<p class="muted">Aucune activité pédagogique disponible pour le moment.</p>
			</section>{/if}
	{/if}
</Modal>
