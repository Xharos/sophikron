<script lang="ts">
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
</script>

<svelte:head
	><title>Cours — {data.establishmentName}</title><meta
		name="robots"
		content="noindex, nofollow"
	/></svelte:head
>
<section class="section container dashboard">
	<h1 class="title is-2">Cours</h1>
	<p>
		Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut
		labore et dolore magna aliqua.
	</p>
</section>
