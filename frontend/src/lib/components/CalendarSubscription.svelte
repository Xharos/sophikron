<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	let { exists }: { exists: boolean } = $props();
	let generated = $state(false);
	let url = $state('');
	let busy = $state(false);
	let message = $state('');
	let confirm = $state(false);
	let ready = $state(false);
	onMount(() => {
		ready = true;
	});
	async function generate(): Promise<void> {
		busy = true;
		message = '';
		try {
			const response = await fetch(resolve('/me/calendar'), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: '{}'
			});
			const result = await response.json();
			if (!response.ok) throw new Error(result.message || 'Abonnement indisponible.');
			url = result.url;
			generated = true;
			confirm = false;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Erreur de connexion.';
		} finally {
			busy = false;
		}
	}
</script>

<section class="workspace-panel" aria-labelledby="calendar-subscription-title">
	<p class="eyebrow">Mon emploi du temps</p>
	<h2 id="calendar-subscription-title" class="title is-5">Abonnement au calendrier</h2>
	<p>
		Retrouvez vos séances dans votre application calendrier. Les mises à jour suivent le rythme de
		votre application.
	</p>
	{#if message}<p role="alert" class="notification is-danger is-light mt-3">{message}</p>{/if}
	{#if url}
		<label class="label mt-3" for="calendar-subscription-url">Votre lien personnel</label>
		<input
			id="calendar-subscription-url"
			class="input"
			value={url}
			readonly
			onclick={(event) => event.currentTarget.select()}
		/>
		<p class="help">
			Copiez ce lien maintenant : il ne sera plus affiché après avoir quitté cette page. Toute
			personne qui le possède peut consulter vos séances.
		</p>
	{/if}
	{#if confirm}
		<p class="mt-3">
			L’ancien lien cessera de fonctionner. Vous devrez remplacer l’abonnement dans votre
			application.
		</p>
		<div class="buttons mt-3">
			<button class="button is-primary" disabled={busy} onclick={generate}
				>Confirmer la régénération</button
			>
			<button class="button is-light" disabled={busy} onclick={() => (confirm = false)}
				>Annuler</button
			>
		</div>
	{:else}
		<button
			class="button is-primary mt-3"
			disabled={busy || !ready}
			onclick={() => {
				if (exists || generated) confirm = true;
				else void generate();
			}}
		>
			{busy ? 'Génération…' : exists || generated ? 'Régénérer mon lien' : 'Générer mon lien'}
		</button>
	{/if}
	<details class="mt-4">
		<summary>Ajouter cet abonnement sur mon téléphone</summary>
		<p class="mt-2">
			iPhone : Calendrier → Calendriers → Ajouter un calendrier → Ajouter un calendrier avec
			abonnement, puis collez le lien.
		</p>
		<p class="mt-2">
			Google Agenda : depuis un ordinateur, Autres agendas → À partir de l’URL. Retrouvez ensuite ce
			calendrier dans l’application Android et activez sa synchronisation.
		</p>
		<p class="help">
			Choisissez un abonnement par URL. Une simple importation de fichier ne recevra pas les
			modifications.
		</p>
	</details>
</section>
