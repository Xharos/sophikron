<script lang="ts">
	import Icon from './Icon.svelte';
	let { subscription }: { subscription: { url: string | null; revoked: boolean } } = $props();
	let message = $state('');
	let copyFailed = $state(false);
	let input: HTMLInputElement | undefined = $state();
	/** Support HTTP LAN access where the modern clipboard API is unavailable. */
	function copySelection(): boolean {
		input?.focus();
		input?.select();
		input?.setSelectionRange(0, input.value.length);
		try {
			return !!input && document.execCommand('copy');
		} catch {
			return false;
		}
	}
	async function copy(): Promise<void> {
		if (!subscription.url) return;
		let copied: boolean;
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(subscription.url);
				copied = true;
			} else copied = copySelection();
		} catch {
			copied = copySelection();
		}
		copyFailed = !copied;
		message = copied
			? 'Lien copié.'
			: 'Copie automatique indisponible. Le lien est sélectionné : copiez-le manuellement.';
	}
</script>

<section
	class="workspace-panel calendar-subscription"
	aria-labelledby="calendar-subscription-title"
>
	<p class="eyebrow">Mon emploi du temps</p>
	<h2 id="calendar-subscription-title" class="title is-5">Abonnement au calendrier</h2>
	<p>Retrouvez vos séances de toute l’année scolaire dans votre application calendrier.</p>
	{#if subscription.revoked}
		<p class="notification is-warning is-light mt-3" role="status">
			Votre abonnement a été révoqué. Il ne transmet plus aucun événement. Contactez un
			administrateur pour obtenir un nouveau lien.
		</p>
	{/if}
	{#if subscription.url}
		<label class="label mt-4" for="calendar-subscription-url">Votre lien personnel</label>
		<div class="subscription-copy">
			<input
				bind:this={input}
				id="calendar-subscription-url"
				class="input"
				value={subscription.url}
				readonly
				onclick={(event) => event.currentTarget.select()}
			/>
			<button class="button is-primary" type="button" onclick={copy}
				><Icon name="copy" />Copier le lien</button
			>
		</div>
		<p class="help">
			Ce lien reste disponible ici. Toute personne qui le possède peut consulter vos séances. Seul
			un administrateur peut le révoquer ou le remplacer.
		</p>
	{/if}
	{#if message}<p class="help" class:has-text-danger={copyFailed} role="status">{message}</p>{/if}
	<p class="help mt-3">
		Sans calendrier autorisé ou séance vous concernant, votre abonnement reste vide.
	</p>
	<details class="mt-4">
		<summary>Ajouter cet abonnement sur mon téléphone</summary>
		<p class="mt-2">
			iPhone : Calendrier → Calendriers → Ajouter un calendrier → Ajouter un calendrier avec
			abonnement, puis collez le lien.
		</p>
		<p class="mt-2">
			Google Agenda : depuis un ordinateur, Autres agendas → À partir de l’URL. Retrouvez ensuite ce
			calendrier dans l’application et activez sa synchronisation.
		</p>
		<p class="help">
			Choisissez un abonnement par URL. Une importation de fichier ne recevra pas les modifications.
			Après remplacement du lien par un administrateur, remplacez aussi l’abonnement dans votre
			application.
		</p>
	</details>
</section>

<style>
	.calendar-subscription {
		margin-top: 1.5rem;
		width: 100%;
		grid-column: 1 / -1;
	}
	.subscription-copy {
		display: flex;
		gap: 0.75rem;
	}
	.subscription-copy input {
		min-width: 0;
	}
	@media (max-width: 600px) {
		.subscription-copy {
			flex-direction: column;
		}
	}
</style>
