<script lang="ts">
	import Icon from './Icon.svelte';
	let {
		offset,
		limit,
		total,
		busy = false,
		onchange
	}: {
		offset: number;
		limit: number;
		total: number;
		busy?: boolean;
		onchange: (offset: number) => void;
	} = $props();
</script>

<nav class="list-pagination" aria-label="Pagination des résultats">
	<p class="muted text-small">
		{total === 0
			? 'Aucun résultat'
			: `${offset + 1}–${Math.min(offset + limit, total)} sur ${total}`}
	</p>
	<div class="buttons mb-0">
		<button
			class="icon-button"
			aria-label="Page précédente"
			disabled={busy || offset === 0}
			onclick={() => onchange(Math.max(0, offset - limit))}><Icon name="previous" /></button
		>
		<button
			class="icon-button"
			aria-label="Page suivante"
			disabled={busy || offset + limit >= total}
			onclick={() => onchange(offset + limit)}><Icon name="next" /></button
		>
	</div>
</nav>
