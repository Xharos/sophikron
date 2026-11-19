<script lang="ts">
	import { resolve } from '$app/paths';

	type Reference = { id: number; title: string };
	let {
		lessonId,
		selected = $bindable(),
		disabled
	}: {
		lessonId: number;
		selected: Reference[];
		disabled: boolean;
	} = $props();
	let query = $state('');
	let options = $state<Reference[]>([]);
	let loading = $state(true);
	let message = $state('');
	const searchId = $props.id();

	$effect(() => {
		const target =
			resolve('/lessons/options') +
			'?' +
			new URLSearchParams({
				resource: 'quizOptions',
				lessonId: String(lessonId),
				q: query.trim()
			});
		const controller = new AbortController();
		loading = true;
		message = '';
		const timer = setTimeout(async () => {
			try {
				const result = await fetch(target, { signal: controller.signal });
				if (!result.ok) throw new Error('La recherche des fiches a échoué.');
				options = (await result.json()) as Reference[];
			} catch (cause) {
				if (!controller.signal.aborted) message = (cause as Error).message;
			} finally {
				if (!controller.signal.aborted) loading = false;
			}
		}, 180);
		return () => {
			clearTimeout(timer);
			controller.abort();
		};
	});
</script>

<fieldset class="field" {disabled}>
	<legend class="label">Fiches du quiz ({selected.length})</legend>
	<div class="tags">
		{#each selected as item (item.id)}
			<span class="tag"
				>{item.title}
				<button
					type="button"
					class="delete is-small"
					aria-label={'Retirer ' + item.title}
					onclick={() => (selected = selected.filter((entry) => entry.id !== item.id))}
				></button>
			</span>
		{/each}
	</div>
	<label class="label is-small" for={searchId}>Rechercher une fiche de la matière</label>
	<input class="input" id={searchId} type="search" bind:value={query} maxlength="160" />
	{#if message}<p class="help is-danger" role="alert">{message}</p>
	{:else if loading}<p class="help" role="status">Recherche en cours…</p>
	{:else}
		<div class="options mt-2">
			{#each options as item (item.id)}
				{@const checked = selected.some((entry) => entry.id === item.id)}
				<label class="checkbox is-block mb-1">
					<input
						type="checkbox"
						{checked}
						disabled={!checked && selected.length >= 50}
						onchange={(event) =>
							(selected = event.currentTarget.checked
								? [...selected, item]
								: selected.filter((entry) => entry.id !== item.id))}
					/>
					{item.title}
				</label>
			{:else}
				<p>Aucune fiche visible ne correspond.</p>
			{/each}
		</div>
		{#if options.length === 50}<p class="help">
				Affinez la recherche pour accéder aux autres fiches.
			</p>{/if}
	{/if}
	<p class="help">De 1 à 50 fiches. Chaque élève les découvre dans un ordre mélangé.</p>
</fieldset>

<style>
	.options {
		max-height: 12rem;
		overflow: auto;
	}
	.tag {
		white-space: normal;
		height: auto;
		min-height: 2em;
	}
</style>
