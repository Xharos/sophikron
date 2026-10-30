<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import AccountAccess from '#lib/components/dashboard/AccountAccess.svelte';
	import { resolve } from '$app/paths';
	import ActivityJournal from '#lib/components/dashboard/ActivityJournal.svelte';
	import ProfileEditor from '#lib/components/dashboard/ProfileEditor.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import CalendarSubscriptionAdmin from '#lib/components/dashboard/CalendarSubscriptionAdmin.svelte';
	import { hasPermission } from '#lib/access';
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
	{#if hasPermission(data.user, 'events.read')}
		{#key data.profile.id}<ActivityJournal userId={data.profile.id} compact />{/key}
	{/if}
	{#if hasPermission(data.user, 'users.manage')}
		{#key data.profile.id}<CalendarSubscriptionAdmin userId={data.profile.id} />
			<AccountAccess
				userId={data.profile.id}
				status={data.profile.status}
				currentUserId={data.user?.id ?? 0}
				onchanged={invalidateAll}
			/>{/key}
	{/if}
</section>
