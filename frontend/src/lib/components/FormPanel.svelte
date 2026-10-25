<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Snippet } from 'svelte';
	let {
		eyebrow,
		title,
		description,
		children
	}: { eyebrow: string; title: string; description: string; children: Snippet } = $props();
</script>

<section class="section form-section">
	<div class="form-shell">
		<a href={resolve('/')} class="back-link">← Accueil</a>
		<div class="box form-panel">
			<p class="eyebrow">{eyebrow}</p>
			<h1 class="title is-2">{title}</h1>
			<p class="form-description">{description}</p>
			{@render children()}
		</div>
	</div>
</section>
