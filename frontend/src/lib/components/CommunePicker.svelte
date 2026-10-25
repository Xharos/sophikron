<script lang="ts">
	import { untrack } from 'svelte';
	import { read } from '#lib/dashboard';
	import type { Commune } from '#lib/types';
	let {
		city = $bindable(null),
		postalCode = $bindable(null),
		communeCode = $bindable(null),
		disabled = false
	}: {
		city: string | null;
		postalCode: string | null;
		communeCode: string | null;
		disabled?: boolean;
	} = $props();
	const initial = untrack(() => (city && communeCode ? `${city} ${postalCode ?? ''}`.trim() : ''));
	let query = $state(initial);
	let selectedLabel = $state(initial);
	let results = $state<Commune[]>([]);
	let loading = $state(false);
	let message = $state('');
	let input: HTMLInputElement;
	const inputId = $props.id();
	$effect(() => {
		const label = city ? `${city} ${postalCode ?? ''}`.trim() : '';
		if (label !== selectedLabel) {
			selectedLabel = label;
			query = label;
		}
	});
	$effect(() => {
		input?.setCustomValidity(
			query && query !== selectedLabel
				? 'Choisissez une commune dans les propositions, ou annulez la recherche.'
				: ''
		);
	});
	$effect(() => {
		const q = query.trim();
		const selected = selectedLabel;
		const controller = new AbortController();
		if (disabled || q === selected || q.length < 2 || (/^\d+$/.test(q) && q.length !== 5)) {
			results = [];
			loading = false;
			return;
		}
		const timer = setTimeout(async () => {
			loading = true;
			message = '';
			try {
				results = await read<Commune[]>('communes', { q }, controller.signal);
			} catch (cause) {
				if (!controller.signal.aborted) message = (cause as Error).message;
			} finally {
				if (!controller.signal.aborted) loading = false;
			}
		}, 250);
		return () => {
			clearTimeout(timer);
			controller.abort();
		};
	});
	function choose(commune: Commune, postcode: string): void {
		city = commune.nom;
		postalCode = postcode;
		communeCode = commune.code;
		selectedLabel = `${commune.nom} ${postcode}`;
		query = selectedLabel;
		results = [];
		input.focus();
	}
</script>

<div class="field commune-picker">
	<label class="label" for={inputId}>Ville et code postal</label>
	<input
		bind:this={input}
		id={inputId}
		class="input"
		bind:value={query}
		{disabled}
		autocomplete="off"
		placeholder="Rechercher une ville ou un code postal…"
	/>
	{#if query !== selectedLabel}<button
			type="button"
			class="button is-text is-small"
			onclick={() => {
				query = selectedLabel;
				message = '';
			}}>Annuler la recherche</button
		>{/if}
	{#if loading}<p class="help" role="status">Recherche des communes…</p>{/if}
	{#if message}<p class="help is-danger" role="alert">
			{message} La commune actuelle est conservée.
		</p>{/if}
	{#if results.length}<div class="commune-results" aria-label="Communes proposées">
			{#each results as commune (commune.code)}{#each commune.codesPostaux as postcode (postcode)}
					<button type="button" onclick={() => choose(commune, postcode)}
						><strong>{commune.nom}</strong><span>{postcode}</span></button
					>
				{/each}{/each}
		</div>{/if}
	{#if city && !disabled}<button
			type="button"
			class="button is-text is-small"
			onclick={() => {
				city = null;
				postalCode = null;
				communeCode = null;
				selectedLabel = '';
				query = '';
			}}>Retirer la commune</button
		>{/if}
	<p class="help">
		Communes françaises · Sélectionnez une proposition pour valider le code postal.
	</p>
</div>
