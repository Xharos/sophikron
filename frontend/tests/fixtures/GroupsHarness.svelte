<script lang="ts">
	import PromotionGroups from '../../src/lib/components/dashboard/PromotionGroups.svelte';
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	const administrator = !new URL(window.location.href).searchParams.has('readonly');
</script>

<main style="padding: 1rem; max-width: 1200px; margin: auto; width: 100%;">
	<PromotionGroups
		promotion={{
			id: 1,
			identifier: 'PTSI',
			year: 2026,
			color: '#4361EE',
			is_active: true
		}}
		{administrator}
		rosterRevision={0}
		ondirty={() => {}}
	/>
</main>
