<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import FormPanel from '#lib/components/FormPanel.svelte';
	import FormMessage from '#lib/components/FormMessage.svelte';
	import PasswordFields from '#lib/components/PasswordFields.svelte';
	import type { PageProps } from './$types';
	let { data, form }: PageProps = $props();
	let busy = $state(false);
</script>

<svelte:head
	><title>Installation — {data.establishmentName}</title><meta
		name="description"
		content={`Créez le compte administrateur permanent de ${data.establishmentName}.`}
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<FormPanel
	eyebrow="Premier départ"
	title="Bienvenue chez vous."
	description="Créez votre compte administrateur permanent. Il remplacera le compte temporaire et vous devrez vous reconnecter."
>
	<FormMessage message={form?.message} />
	{#if form?.success}
		<div class="success-panel" role="status">
			<h2 class="title is-4">Votre compte est prêt.</h2>
			<p>Votre identifiant permanent :</p>
			<strong class="title is-3 block mt-3">{form.username}</strong>
			<p class="help mt-3">Vous pouvez aussi vous connecter avec votre adresse email.</p>
		</div>
		<a class="button is-primary is-fullwidth mt-5" href={resolve('/login?notice=setup')}
			>Me connecter</a
		>
	{:else}<form
			method="POST"
			use:enhance={() => {
				busy = true;
				return async ({ update }) => {
					try {
						await update({ invalidateAll: false });
					} finally {
						busy = false;
					}
				};
			}}
			aria-busy={busy}
		>
			<div class="field">
				<label class="label" for="first_name">Prénom</label><input
					class="input"
					id="first_name"
					name="first_name"
					autocomplete="given-name"
					maxlength="100"
					required
				/>
			</div>
			<div class="field">
				<label class="label" for="last_name">Nom</label><input
					class="input"
					id="last_name"
					name="last_name"
					autocomplete="family-name"
					maxlength="100"
					required
				/>
			</div>
			<p class="help mb-4">
				Votre identifiant sera créé automatiquement à partir de vos nom et prénom.
			</p>
			<div class="field">
				<label class="label" for="email">Adresse email</label><input
					class="input"
					id="email"
					name="email"
					type="email"
					autocomplete="email"
					maxlength="254"
					required
				/>
			</div>
			<PasswordFields />
			<button
				class="button is-primary is-fullwidth mt-5"
				class:is-loading={busy}
				disabled={busy}
				type="submit">Créer mon compte administrateur</button
			>
		</form>{/if}
</FormPanel>
