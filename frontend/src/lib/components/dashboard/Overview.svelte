<script lang="ts">
	import StatisticsPanel from '../statistics/StatisticsPanel.svelte';
	import ActivityJournal from './ActivityJournal.svelte';
	let journalRevision = $state(0);
</script>

<div class="section-intro">
	<div>
		<p class="eyebrow">Vue d’ensemble</p>
		<h2 class="title is-3 mb-2">Tout votre établissement, en un regard.</h2>
		<p class="muted">Comptes, connexions et ressources pédagogiques.</p>
	</div>
</div>
<StatisticsPanel onrefresh={() => (journalRevision += 1)} />
<ActivityJournal revision={journalRevision} />
