<script lang="ts">
	import { resolve } from '$app/paths';
	import { enhance } from '$app/forms';
	import { formatDate, statusLabels } from '#lib/dashboard';
	import RoleBadges from '#lib/components/RoleBadges.svelte';
	import FormMessage from '#lib/components/FormMessage.svelte';
	import PasswordFields from '#lib/components/PasswordFields.svelte';
	import PromotionTag from '#lib/components/PromotionTag.svelte';
	import SchoolProfileView from '#lib/components/SchoolProfileView.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import CalendarSubscription from '#lib/components/CalendarSubscription.svelte';
	import type { PageProps } from './$types';
	let { data, form }: PageProps = $props();
	let busy = $state(false);
	let passwordOpen = $state(false);
	$effect(() => {
		if (form?.message) passwordOpen = true;
	});
</script>

<svelte:head
	><title>Mon compte — {data.establishmentName}</title><meta
		name="description"
		content="Votre identité, votre parcours scolaire et la sécurité de votre compte."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container personal-page">
	<header class="personal-hero">
		<div class="avatar large">
			{data.account.first_name?.slice(0, 1) ?? 'S'}{data.account.last_name?.slice(0, 1)}
		</div>
		<div class="personal-intro">
			<p class="eyebrow">Mon espace personnel</p>
			<h1 class="title is-2 mb-2">
				{data.account.first_name ?? data.account.username}
				{data.account.last_name ?? ''}
			</h1>
			<p class="muted">
				@{data.account.username} · <RoleBadges roles={data.account.roles} />
			</p>
			{#if data.account.email}<p class="personal-email">
					<Icon name="email" />{data.account.email}
				</p>{/if}
		</div>
		{#if data.account.is_bootstrap}<a class="button is-primary" href={resolve('/setup')}
				>Terminer l’installation</a
			>{:else}<button class="button is-light" onclick={() => (passwordOpen = true)}
				><Icon name="lock" />Mot de passe</button
			>{/if}
	</header>
	{#if !data.account.is_bootstrap}
		<section class="workspace-panel personal-promotions">
			<div>
				<p class="eyebrow">Mon parcours</p>
				<h2 class="title is-5 mb-0"><Icon name="promotions" />Mes promotions</h2>
			</div>
			<div class="profile-buttons">
				{#each data.promotions as promotion (promotion.id)}<PromotionTag
						{promotion}
					/>{/each}{#if data.promotions.length === 0}<p class="muted">
						Aucune promotion affectée.
					</p>{/if}
			</div>
		</section>
	{/if}
	{#if data.profile}<SchoolProfileView account={data.profile} />{/if}
	{#if data.calendarSubscription}<CalendarSubscription
			exists={data.calendarSubscription.exists}
		/>{/if}
	<section class="workspace-panel account-activity">
		<p class="eyebrow">Activité et sécurité</p>
		<h2 class="title is-5"><Icon name="clock" />Les repères de votre compte</h2>
		<div class="activity-grid">
			<div>
				<span>Dernière connexion</span><strong>{formatDate(data.account.last_login_at)}</strong>
			</div>
			<div>
				<span
					>Connexion{data.account.login_count === 1 ? '' : 's'} réussie{data.account.login_count ===
					1
						? ''
						: 's'}</span
				><strong>{data.account.login_count}</strong>
			</div>
			<div><span>Compte créé le</span><strong>{formatDate(data.account.created_at)}</strong></div>
			<div>
				<span>Dernière mise à jour</span><strong>{formatDate(data.account.updated_at)}</strong>
			</div>
			<div>
				<span>Mot de passe modifié</span><strong
					>{formatDate(data.account.password_changed_at)}</strong
				>
			</div>
			<div>
				<span>Email vérifié</span><strong
					>{data.account.email_verified
						? formatDate(data.account.email_verified_at)
						: 'Non vérifié'}</strong
				>
			</div>
		</div>
		<p class="help mt-4">
			{statusLabels[data.account.status]} · Dates à l’heure de Paris. La dernière connexion correspond
			à une authentification réussie.
		</p>
	</section>
</section>
{#if passwordOpen && !data.account.is_bootstrap}<Modal
		title="Changer mon mot de passe"
		description="Après modification, toutes vos sessions seront fermées."
		{busy}
		onclose={() => (passwordOpen = false)}
	>
		<FormMessage message={form?.message} />
		<form
			method="POST"
			use:enhance={() => {
				busy = true;
				return async ({ update }) => {
					try {
						await update();
					} finally {
						busy = false;
					}
				};
			}}
			aria-busy={busy}
		>
			<div class="field">
				<label class="label" for="current-password">Mot de passe actuel</label><input
					class="input"
					id="current-password"
					name="current_password"
					type="password"
					autocomplete="current-password"
					maxlength="128"
					required
				/>
			</div>
			<PasswordFields />
			<div class="dialog-actions">
				<button
					class="button is-light"
					type="button"
					disabled={busy}
					onclick={() => (passwordOpen = false)}>Annuler</button
				><button class="button is-primary" type="submit" class:is-loading={busy} disabled={busy}
					><Icon name="lock" />Modifier mon mot de passe</button
				>
			</div>
		</form>
	</Modal>{/if}
