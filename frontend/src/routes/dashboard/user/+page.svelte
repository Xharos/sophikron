<script lang="ts">
	import { resolve } from '$app/paths';
	import ProfileEditor from '#lib/components/dashboard/ProfileEditor.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
</script>

<svelte:head
	><title>Fiche du compte — {data.establishmentName}</title><meta
		name="description"
		content="Fiche scolaire privée et informations du compte."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container full-profile-page">
	<a class="button is-light mb-5" href={resolve('/dashboard?tab=accounts')}
		><Icon name="previous" />Retour aux comptes</a
	>
	{#key data.profile.id}<ProfileEditor
			profile={data.profile}
			currentUserId={data.user?.id ?? 0}
		/>{/key}
</section>
