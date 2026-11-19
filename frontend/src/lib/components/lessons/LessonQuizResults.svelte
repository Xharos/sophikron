<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';

	type Card = { id: number; title: string; version: number; attempts: number; solved: boolean };
	type Pupil = {
		id: number;
		name: string;
		completed: number;
		total: number;
		trials: number;
		status: 'not_started' | 'started' | 'completed';
		promotion_ids: number[];
		cards: Card[];
	};
	type Results = { promotions: { id: number; label: string }[]; pupils: Pupil[] };
	const status = { not_started: 'Non commencé', started: 'En cours', completed: 'Terminé' };

	let { lessonId, elementId }: { lessonId: number; elementId: number } = $props();
	let data = $state<Results | null>(null);
	let message = $state('');
	let promotion = $state(0);
	const filterId = $props.id();
	const pupils = $derived(
		data?.pupils.filter((pupil) => !promotion || pupil.promotion_ids.includes(promotion)) ?? []
	);
	const started = $derived(pupils.filter((pupil) => pupil.status !== 'not_started').length);
	const completed = $derived(pupils.filter((pupil) => pupil.status === 'completed').length);
	const cards = $derived.by(() => {
		const totals = new SvelteMap<
			string,
			{
				title: string;
				version: number;
				answered: number;
				first: number;
				solved: number;
				attempts: number;
			}
		>();
		for (const pupil of pupils) {
			for (const card of pupil.cards) {
				const key = card.id + ':' + card.version;
				const summary = totals.get(key) ?? {
					title: card.title,
					version: card.version,
					answered: 0,
					first: 0,
					solved: 0,
					attempts: 0
				};
				summary.answered += Number(card.attempts > 0);
				summary.first += Number(card.solved && card.attempts === 1);
				summary.solved += Number(card.solved);
				if (card.solved) summary.attempts += card.attempts;
				totals.set(key, summary);
			}
		}
		return [...totals];
	});
	const percent = new Intl.NumberFormat('fr', { style: 'percent', maximumFractionDigits: 1 });
	const number = new Intl.NumberFormat('fr', { maximumFractionDigits: 1 });

	onMount(() => {
		const controller = new AbortController();
		const query = new URLSearchParams({
			resource: 'quizResults',
			lessonId: String(lessonId),
			elementId: String(elementId)
		});
		void fetch(resolve('/lessons/options') + '?' + query, { signal: controller.signal })
			.then(async (result) => {
				if (!result.ok) throw new Error('Impossible de charger les résultats.');
				data = (await result.json()) as Results;
			})
			.catch((cause: Error) => {
				if (!controller.signal.aborted) message = cause.message;
			});
		return () => controller.abort();
	});
</script>

<div class="mt-3">
	{#if message}<p class="help is-danger" role="alert">{message}</p>
	{:else if !data}<p role="status">Chargement des résultats…</p>
	{:else}
		<label class="label is-small" for={filterId}>Promotion</label>
		<div class="select is-small mb-3">
			<select id={filterId} bind:value={promotion}>
				<option value={0}>Toutes les promotions autorisées</option>
				{#each data.promotions as item (item.id)}<option value={item.id}>{item.label}</option
					>{/each}
			</select>
		</div>
		{#if pupils.length}
			<p class="mb-3">
				{pupils.length} attendu(s) · {started} commencé(s) · {completed} terminé(s) · {percent.format(
					completed / pupils.length
				)} du public attendu
			</p>
			<div class="table-container">
				<table class="table is-fullwidth is-narrow">
					<thead
						><tr><th>Élève</th><th>Premier passage</th><th>Progression</th><th>Essais</th></tr
						></thead
					>
					<tbody>
						{#each pupils as pupil (pupil.id)}
							<tr>
								<th scope="row">
									{#if pupil.cards.length}
										<details>
											<summary>{pupil.name}</summary>
											<ul>
												{#each pupil.cards as card (card.id)}
													<li>
														{card.title} · {card.attempts} essai(s){card.solved ? ' · réussie' : ''}
													</li>
												{/each}
											</ul>
										</details>
									{:else}{pupil.name}{/if}
								</th>
								<td>{status[pupil.status]}</td><td>{pupil.completed}/{pupil.total}</td><td
									>{pupil.trials}</td
								>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if cards.length}
				<h5 class="title is-6">Résultats par fiche</h5>
				<div class="table-container">
					<table class="table is-fullwidth is-narrow">
						<thead
							><tr
								><th>Fiche</th><th>Réussite au premier essai</th><th>Essais moyens pour réussir</th
								></tr
							></thead
						>
						<tbody>
							{#each cards as [key, card] (key)}
								<tr>
									<th scope="row">{card.title} <small>· v{card.version + 1}</small></th>
									<td>{card.answered ? percent.format(card.first / card.answered) : '—'}</td>
									<td>{card.solved ? number.format(card.attempts / card.solved) : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{:else}<p>Aucun élève actuellement attendu dans cette sélection.</p>{/if}
	{/if}
</div>
