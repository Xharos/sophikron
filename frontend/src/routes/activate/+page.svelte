<script lang="ts">
	import { onMount } from 'svelte';
	import { enhance } from '$app/forms';
	import FormPanel from '#lib/components/FormPanel.svelte';
	import FormMessage from '#lib/components/FormMessage.svelte';
	import PasswordFields from '#lib/components/PasswordFields.svelte';
	import type { PageProps } from './$types';
	let { data, form }: PageProps = $props();
	let token = $state('');
	let busy = $state(false);
	onMount(() => {
		token = new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '';
		// Remove the activation credential from the address bar and current history entry.
		window.history.replaceState(window.history.state, '', window.location.pathname);
	});
</script>

<svelte:head
	><title>Définir mon mot de passe — {data.establishmentName}</title><meta
		name="description"
		content={`Définissez ou renouvelez votre mot de passe ${data.establishmentName} avec votre invitation.`}
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<FormPanel
	eyebrow="Vous êtes invité"
	title={`Votre accès à ${data.establishmentName}.`}
	description="Choisissez un mot de passe pour activer votre compte ou renouveler votre accès."
>
	<FormMessage message={form?.message} />
	<form
		method="POST"
		use:enhance={() => {
			busy = true;
			return async ({ update }) => {
				try {
					await update({ reset: false });
				} finally {
					busy = false;
				}
			};
		}}
		aria-busy={busy}
	>
		<div class="field">
			<label class="label" for="token">Jeton d’invitation</label><input
				class="input"
				id="token"
				name="token"
				bind:value={token}
				autocomplete="off"
				maxlength="128"
				spellcheck="false"
				required
			/>
			<p class="help">Renseigné depuis votre lien. Vous pouvez aussi le coller ici.</p>
		</div>
		<PasswordFields />
		<button
			class="button is-primary is-fullwidth mt-5"
			class:is-loading={busy}
			disabled={busy}
			type="submit">Enregistrer mon mot de passe <span aria-hidden="true">↗</span></button
		>
	</form>
</FormPanel>
