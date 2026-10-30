<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		title,
		subtitle = '',
		value = '',
		caption = '',
		children
	}: {
		title: string;
		subtitle?: string;
		value?: string;
		caption?: string;
		children: Snippet;
	} = $props();
</script>

<section class="workspace-panel stat-card" aria-label={title}>
	<header>
		<h3 class="title is-5 mb-1">{title}</h3>
		{#if subtitle}<p class="stat-subtitle">{subtitle}</p>{/if}
	</header>
	{#if value}<div class="stat-kpi">{value}<span>{caption}</span></div>{/if}
	<div class="stat-body">{@render children()}</div>
</section>

<style>
	.stat-card {
		min-width: 0;
		padding: 1.4rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		border-top: 3px solid var(--color-soft);
	}
	.stat-card header {
		min-height: 2.6rem;
	}
	.stat-subtitle {
		font-size: 0.76rem;
		color: var(--color-muted);
		line-height: 1.45;
	}
	.stat-kpi {
		font-size: 2.1rem;
		font-weight: 700;
		letter-spacing: -0.05em;
		line-height: 1.15;
	}
	.stat-kpi span {
		display: block;
		font-size: 0.75rem;
		font-weight: 400;
		color: var(--color-muted);
		letter-spacing: 0;
		margin-top: 0.3rem;
	}
	.stat-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}
</style>
