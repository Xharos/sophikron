<script lang="ts">
	import { resolve } from '$app/paths';
	import Icon from '../Icon.svelte';
	let { promotionId }: { promotionId: number } = $props();
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
	<p class="muted text-small">
		Le PDF s’ouvre dans un nouvel onglet pour l’enregistrer ou l’imprimer.
	</p>
</section>
