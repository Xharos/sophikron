<script lang="ts">
	import type { AccessInvitation } from '#lib/types';
	import { formatDate } from '#lib/dashboard';
	import Icon from './Icon.svelte';
	let { invitation }: { invitation: AccessInvitation } = $props();
	let copied = $state(false);
	let copyError = $state(false);
	async function copy(): Promise<void> {
		try {
			await navigator.clipboard.writeText(invitation.link ?? '');
			copied = true;
		} catch {
			copyError = true;
		}
	}
</script>

<div class="invitation-notice" role="status">
	<strong
		>{invitation.delivery === 'email'
			? 'Invitation envoyée par email'
			: 'Invitation prête à partager'}</strong
	>
	<p class="text-small muted mt-2">
		Valable jusqu’au {formatDate(invitation.expires_at)}. Les anciens liens sont invalidés.
	</p>
	{#if invitation.link}
		<label class="label mt-3" for="invitation-link">Lien personnel</label>
		<input
			id="invitation-link"
			class="input text-small"
			value={invitation.link}
			readonly
			onclick={(event) => event.currentTarget.select()}
		/>
		<button class="button is-light mt-3" type="button" onclick={copy}
			><Icon name={copied ? 'check' : 'link'} />{copied ? 'Lien copié' : 'Copier le lien'}</button
		>
		{#if copyError}<p class="help">Sélectionnez le lien pour le copier manuellement.</p>{/if}
	{/if}
</div>
