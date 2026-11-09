<script lang="ts">
	let {
		count,
		color,
		href,
		onopen
	}: {
		count: number;
		color: 'is-success' | 'is-warning' | 'is-danger';
		href?: string;
		onopen?: () => void;
	} = $props();
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- Callers resolve the calendar route. -->
{#if href}
	<a class="button is-small {color}" {href} aria-label={'Points à vérifier (' + count + ')'}
		>⚠ {count}</a
	>
{:else}
	<button
		class="button is-small {color}"
		onclick={onopen}
		aria-label={'Points à vérifier (' + count + ')'}>⚠ {count}</button
	>
{/if}
