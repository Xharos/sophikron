<script lang="ts">
	import type { Promotion } from '#lib/types';
	import { resolve } from '$app/paths';
	import Icon from './Icon.svelte';
	let {
		promotion,
		linked = false
	}: {
		promotion: Pick<Promotion, 'identifier' | 'year' | 'color'> & {
			id?: number;
			is_active?: boolean;
		};
		linked?: boolean;
	} = $props();
</script>

{#snippet content()}
	<span class="promotion-dot" aria-hidden="true"></span>{promotion.identifier}
	<span class="muted">{promotion.year}</span>
	{#if promotion.is_active === false}<span class="muted">· archivée</span>{/if}
	{#if linked}<Icon name="open" size={11} />{/if}
{/snippet}
{#if linked && promotion.id}
	<a
		class="promotion-tag"
		style={`--promotion-color: ${promotion.color}`}
		href={resolve(`/dashboard?tab=promotions&promotion=${promotion.id}&edit=1`)}
		title={`Configurer ${promotion.identifier} ${promotion.year}`}
	>
		{@render content()}
	</a>
{:else}
	<span class="promotion-tag" style={`--promotion-color: ${promotion.color}`}
		>{@render content()}</span
	>
{/if}

<style>
	a {
		text-decoration: none;
		color: inherit;
	}
	a:hover {
		text-decoration: underline;
	}
	a:focus-visible {
		outline: 2px solid var(--promotion-color);
		outline-offset: 3px;
	}
</style>
