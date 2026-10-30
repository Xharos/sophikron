<script lang="ts">
	import { resolve } from '$app/paths';
	import Icon from '../Icon.svelte';
	import { read } from '#lib/dashboard';
	import type { PromotionGroupsData } from '#lib/groups';
	let { promotionId, revision = 0 }: { promotionId: number; revision?: number } = $props();
	let available = $state<string[]>([]);
	$effect(() => {
		const id = promotionId;
		void revision;
		available = [];
		const controller = new AbortController();
		void Promise.all([
			read<PromotionGroupsData>('promotionGroups', { id }, controller.signal),
			read<{ groups: { id: number }[] }>('customPromotionGroups', { id }, controller.signal)
		])
			.then(([partitions, custom]) => {
				if (!controller.signal.aborted)
					available = [
						...partitions.partitions
							.filter((partition) => partition.groups.length)
							.map((partition) => partition.kind),
						...(custom.groups.length ? ['custom'] : [])
					];
			})
			.catch(() => {
				/* Keep group downloads hidden when availability cannot be verified. */
			});
		return () => controller.abort();
	});
	const variants = [
		{ value: 'halves', label: 'Demi-groupes' },
		{ value: 'thirds', label: 'Tiers de groupe' },
		{ value: 'kholles', label: 'Groupes de khôlle' },
		{ value: 'custom', label: 'Groupes personnalisés' },
		{ value: 'global', label: 'Liste globale' }
	];
</script>

<section class="workspace-panel mt-5" aria-label="Feuille de présence">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Documents de la promotion</p>
			<h3 class="title is-4 mb-2">Feuille de présence</h3>
			<p class="muted text-small">
				Liste complète des élèves au format A4, avec une colonne de remarques à remplir. Les élèves
				archivés figurent à la fin, avec leurs noms barrés.
			</p>
		</div>
		<a
			class="button is-light"
			href={resolve(`/dashboard/attendance?promotionId=${promotionId}`)}
			target="_blank"
			rel="noopener noreferrer"><Icon name="pdf" />Ouvrir le PDF</a
		>
	</div>
	<div class="buttons mt-4" aria-label="Autres documents PDF">
		{#each variants as variant (variant.value)}
			{#if variant.value === 'global' || available.includes(variant.value)}
				<a
					class="button is-light"
					href={resolve(
						`/dashboard/attendance?promotionId=${promotionId}&variant=${variant.value}`
					)}
					target="_blank"
					rel="noopener noreferrer"><Icon name="pdf" />{variant.label}</a
				>
			{/if}
		{/each}
	</div>
	<p class="muted text-small">
		Le PDF s’ouvre dans un nouvel onglet pour l’enregistrer ou l’imprimer.
	</p>
</section>
