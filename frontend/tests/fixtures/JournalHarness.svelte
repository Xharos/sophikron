<script lang="ts">
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	import ActivityJournal from '../../src/lib/components/dashboard/ActivityJournal.svelte';
	import MembershipPicker from '../../src/lib/components/dashboard/MembershipPicker.svelte';
	import Icon from '../../src/lib/components/Icon.svelte';
	let membership = $state(false);
</script>

<main class="p-3">
	<aside class="workspace-sidebar mb-4" style="max-width: 240px; position: static;">
		<nav aria-label="Navigation de test">
			<button class="active"><Icon name="overview" /><span>Vue d’ensemble</span></button>
			<button><Icon name="accounts" /><span>Comptes</span></button>
		</nav>
	</aside>
	<ActivityJournal />
	<button class="button mt-4" onclick={() => (membership = true)}>Ajouter des membres</button>
	{#if membership}<MembershipPicker
			promotion={{ id: 1, year: 2026, identifier: 'PT', color: '#244bc1', is_active: true }}
			onclose={() => (membership = false)}
			onsaved={() => {}}
		/>{/if}
</main>
