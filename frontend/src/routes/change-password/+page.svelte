<script lang="ts">
	import { enhance } from '$app/forms';
	import FormPanel from '#lib/components/FormPanel.svelte';
	import FormMessage from '#lib/components/FormMessage.svelte';
	import PasswordFields from '#lib/components/PasswordFields.svelte';
	import type { PageProps } from './$types';
	let { data, form }: PageProps = $props();
	let busy = $state(false);
</script>

<svelte:head
	><title>Mot de passe — {data.establishmentName}</title><meta
		name="description"
		content={`Changez le mot de passe de votre compte ${data.establishmentName}.`}
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<FormPanel
	eyebrow="Mon compte"
	title="Un nouveau mot de passe."
	description="Après modification, toutes vos sessions seront fermées. Vous pourrez vous reconnecter avec votre nouveau mot de passe."
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
		<button
			class="button is-primary is-fullwidth mt-5"
			class:is-loading={busy}
			disabled={busy}
			type="submit">Modifier mon mot de passe</button
		>
	</form>
</FormPanel>
