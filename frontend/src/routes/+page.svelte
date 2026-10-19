<script lang="ts">
	let count = $state(0);
</script>

<svelte:head>
	<title>Sophikron — Accueil</title>
	<meta name="description" content="Sophikron, plateforme pédagogique." />
</svelte:head>

<section class="section">
	<div class="container">
		<div class="notification is-primary is-light">Bulma est correctement chargé.</div>

		<h1 class="title is-1">Sophikron</h1>
		<p class="subtitle is-4">La plateforme pédagogique.</p>

		<div class="box">
			<p class="mb-4">Ceci est un exemple de composant Bulma.</p>

			<button class="button is-primary" onclick={() => count++}>
				Cliqué {count} fois
			</button>
		</div>
	</div>
</section>
