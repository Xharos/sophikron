<script lang="ts">
	import type { PageProps } from './$types';
	let { data, form }: PageProps = $props();
</script>

<svelte:head
	><title>Déconnexion — {data.establishmentName}</title><meta
		name="robots"
		content="noindex, nofollow"
	/></svelte:head
>
<section class="section container">
	<h1 class="title">Se déconnecter</h1>
	{#if form?.message}<p class="notification is-danger is-light" role="alert">{form.message}</p>{/if}
	<form method="POST">
		<button class="button is-primary" type="submit">Confirmer la déconnexion</button>
	</form>
</section>
