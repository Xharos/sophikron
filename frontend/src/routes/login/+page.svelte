<script lang="ts">
	import { enhance } from '$app/forms';
	import { page } from '$app/state';
	import FormPanel from '#lib/components/FormPanel.svelte';
	import FormMessage from '#lib/components/FormMessage.svelte';
	import type { PageProps } from './$types';
	let { data, form }: PageProps = $props();
	let busy = $state(false);
	const notices: Record<string, string> = {
		setup: 'Votre compte administrateur est prêt. Connectez-vous avec vos nouveaux identifiants.',
		password: 'Mot de passe modifié. Toutes vos sessions ont été fermées. Reconnectez-vous.',
		activated: 'Votre mot de passe est enregistré. Vous pouvez vous connecter.',
		logout: 'Vous êtes déconnecté.'
	};
</script>

<svelte:head
	><title>Connexion — {data.establishmentName}</title><meta
		name="description"
		content={`Connectez-vous à votre espace ${data.establishmentName}.`}
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<FormPanel
	eyebrow="Bienvenue"
	title="Votre espace vous attend."
	description="Connectez-vous avec votre identifiant ou votre adresse email."
>
	<FormMessage message={notices[page.url.searchParams.get('notice') ?? '']} success />
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
			<label class="label" for="identifier">Identifiant ou email</label>
			<div class="control">
				<input
					class="input"
					id="identifier"
					name="identifier"
					autocomplete="username"
					maxlength="254"
					required
				/>
			</div>
		</div>
		<div class="field">
			<label class="label" for="password">Mot de passe</label>
			<div class="control">
				<input
					class="input"
					id="password"
					name="password"
					type="password"
					autocomplete="current-password"
					maxlength="128"
				/>
			</div>
		</div>
		<button
			class="button is-primary is-fullwidth mt-5"
			class:is-loading={busy}
			disabled={busy}
			type="submit">Se connecter <span aria-hidden="true">↗</span></button
		>
	</form>
	<p class="help mt-5">
		Première connexion ? Ouvrez le lien d’invitation transmis par votre administrateur.
	</p>
</FormPanel>
