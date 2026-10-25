<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
</script>

<svelte:head
	><title>Erreur {page.status} — {page.data.establishmentName}</title><meta
		name="robots"
		content="noindex, nofollow"
	/></svelte:head
>
<section class="section container about-page">
	<p class="eyebrow">Erreur {page.status}</p>
	<h1 class="title is-2">La page n’est pas disponible.</h1>
	<p class="mb-5">{page.error?.message ?? 'Réessayez dans quelques instants.'}</p>
	<a class="button is-primary" href={resolve('/')}>Revenir à l’accueil</a>
</section>
