<script lang="ts">
	import { onMount } from 'svelte';
	import { command, read } from '#lib/dashboard';
	import Modal from '../Modal.svelte';
	let { userId }: { userId?: number } = $props();
	type Action = 'revoke' | 'regenerate';
	type Status = { eligible: boolean; exists: boolean; revoked: boolean };
	let status = $state<Status | null>(null);
	let category = $state('user');
	let confirmation = $state<Action | null>(null);
	let busy = $state(false);
	let loading = $state(true);
	let message = $state('');
	let success = $state('');
	const labels: Record<string, string> = {
		user: 'élèves',
		teacher: 'enseignants',
		kholleur: 'khôlleurs'
	};
	onMount(async () => {
		if (userId === undefined) {
			loading = false;
			return;
		}
		try {
			status = await read<Status>('calendarSubscription', { id: userId });
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	});
	async function perform(): Promise<void> {
		if (!confirmation) return;
		busy = true;
		message = '';
		success = '';
		try {
			if (userId !== undefined) {
				status = await command<Status>('calendarSubscription', {
					id: userId,
					data: { action: confirmation }
				});
				success =
					confirmation === 'revoke'
						? 'Abonnement révoqué.'
						: 'Nouveau lien disponible dans le compte personnel du membre.';
			} else {
				const result = await command<{ affected: number }>('calendarSubscriptionsBulk', {
					data: { category, action: confirmation }
				});
				success = `${result.affected} compte(s) traité(s).`;
			}
			confirmation = null;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<section class="workspace-panel mt-5" aria-label="Gestion des abonnements calendrier">
	<p class="eyebrow">Emplois du temps</p>
	<h2 class="title is-5">
		{userId === undefined ? 'Abonnements calendrier par catégorie' : 'Abonnement au calendrier'}
	</h2>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if success}<p class="notification is-success is-light" role="status">{success}</p>{/if}
	{#if loading}<p role="status">Chargement de l’abonnement…</p>{/if}
	{#if userId === undefined}
		<p>
			Ces actions concernent tous les membres actifs de la catégorie qui se sont déjà connectés. Un
			membre cumulant plusieurs rôles est concerné par chacune de ses catégories.
		</p>
		<div class="field mt-4">
			<label class="label" for="subscription-category">Catégorie</label>
			<div class="select">
				<select
					id="subscription-category"
					bind:value={category}
					disabled={busy || confirmation !== null}
					><option value="user">Élèves</option><option value="teacher">Enseignants</option><option
						value="kholleur">Khôlleurs</option
					></select
				>
			</div>
		</div>
	{:else if status}
		<p>
			{!status.eligible
				? 'Le compte doit être actif et s’être connecté au moins une fois.'
				: status.revoked
					? 'Abonnement révoqué.'
					: status.exists
						? 'Abonnement autorisé.'
						: 'Le lien sera créé à la prochaine connexion ou visite du compte personnel.'}
		</p>
	{/if}
	<p class="help mt-2">
		Le lien personnel est visible uniquement dans le /me de son propriétaire. La révocation suspend
		son accès. Générer un nouveau lien rétablit l’accès et invalide définitivement l’ancien.
	</p>
	<div class="buttons mt-4">
		<button
			class="button is-danger is-light"
			disabled={busy || loading || (userId !== undefined && (!status?.eligible || status.revoked))}
			onclick={() => (confirmation = 'revoke')}
			>{userId === undefined ? 'Révoquer les abonnements' : 'Révoquer le lien'}</button
		>
		<button
			class="button is-primary is-light"
			disabled={busy || loading || (userId !== undefined && !status?.eligible)}
			onclick={() => (confirmation = 'regenerate')}
			>{userId === undefined
				? 'Générer de nouveaux liens'
				: status?.revoked
					? 'Réactiver avec un nouveau lien'
					: 'Générer un nouveau lien'}</button
		>
	</div>
</section>
{#if confirmation}
	<Modal
		title={confirmation === 'revoke' ? 'Révoquer l’abonnement' : 'Remplacer le lien d’abonnement'}
		{busy}
		onclose={() => (confirmation = null)}
	>
		<p>
			{userId === undefined
				? `Tous les ${labels[category]} actifs déjà connectés seront concernés.`
				: 'Ce compte sera concerné.'}
		</p>
		<p class="mt-3">
			{confirmation === 'revoke'
				? 'Les liens ne transmettront plus aucun événement. Les applications peuvent supprimer les événements après actualisation. Les copies déjà téléchargées ne peuvent pas être effacées à distance.'
				: 'Chaque membre disposera d’un nouveau lien dans son /me. Les anciens liens ne transmettront plus rien. Les membres devront remplacer leur abonnement dans leur application calendrier.'}
		</p>
		{#if message}<p class="notification is-danger is-light mt-3" role="alert">{message}</p>{/if}
		<div class="buttons mt-4">
			<button class="button is-primary" class:is-loading={busy} disabled={busy} onclick={perform}
				>Confirmer</button
			><button class="button is-light" disabled={busy} onclick={() => (confirmation = null)}
				>Annuler</button
			>
		</div>
	</Modal>
{/if}
