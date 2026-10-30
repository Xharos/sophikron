<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import lostCat from '#lib/assets/lost-cat.svg';
	import Icon from './Icon.svelte';

	const messages = [
		'Cette page a filé entre les pattes.',
		'Cette page est partie réviser dans un endroit très discret.',
		'Même le chat sèche. Et pourtant, il a neuf vies pour chercher.'
	];
	let message = $state(messages[0]);
	onMount(() => {
		message = messages[Math.floor(Math.random() * messages.length)];
	});
</script>

<section class="not-found">
	<img
		src={lostCat}
		width="560"
		height="360"
		alt="Un chat tricolore se lèche la patte près d’un panneau 404 cassé."
	/>
	<p class="not-found-code">ERREUR 404</p>
	<h1 class="title">On s’est un peu perdus.</h1>
	<p class="not-found-message">{message}</p>
	<a class="button is-primary" href={resolve('/')}>
		Retour à l’accueil <Icon name="arrow" size={15} />
	</a>
</section>

<style>
	.not-found {
		display: flex;
		flex-direction: column;
		align-items: center;
		max-width: 46rem;
		margin-inline: auto;
		padding: clamp(1.5rem, 4vw, 3.5rem) 1.25rem;
		text-align: center;
	}
	img {
		display: block;
		width: min(100%, 30rem);
		height: auto;
	}
	.not-found-code {
		margin: 0.25rem 0 0.65rem;
		color: var(--color-primary);
		font-size: 0.75rem;
		font-weight: 700;
		letter-spacing: 0.15em;
	}
	h1 {
		margin: 0 0 0.85rem;
		font-size: clamp(1.75rem, 4vw, 2.5rem);
	}
	.not-found-message {
		max-width: 30rem;
		min-height: 3em;
		margin: 0 0 1.5rem;
		color: var(--color-muted);
		line-height: 1.5;
	}
	.button {
		gap: 0.6rem;
		border-radius: 999px;
	}
</style>
