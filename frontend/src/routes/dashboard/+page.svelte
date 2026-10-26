<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { hasPermission } from '#lib/access';
	import Icon from '#lib/components/Icon.svelte';
	import Overview from '#lib/components/dashboard/Overview.svelte';
	import SubjectsPanel from '#lib/components/dashboard/SubjectsPanel.svelte';
	import TeachingTeamPanel from '#lib/components/dashboard/TeachingTeamPanel.svelte';
	import SitePanel from '#lib/components/dashboard/SitePanel.svelte';
	import PromotionsPanel from '#lib/components/dashboard/PromotionsPanel.svelte';
	import AccountsPanel from '#lib/components/dashboard/AccountsPanel.svelte';
	import StatisticsPanel from '#lib/components/statistics/StatisticsPanel.svelte';
	import type { PageProps } from './$types';
	import type { Promotion } from '#lib/types';
	import type { Subject } from '#lib/site';
	let { data }: PageProps = $props();
	const canReadStudents = $derived(hasPermission(data.user, 'teaching.read'));
	let initialPromotion = $state<Promotion | undefined>(
		untrack(() => data.initialPromotion ?? undefined)
	);
	let editPromotion = $state(untrack(() => data.editPromotion));
	let initialSubject = $state<Subject | undefined>();
	let section = $state(
		untrack(() =>
			[
				'overview',
				'promotions',
				'accounts',
				'subjects',
				'team',
				'configuration',
				'statistics'
			].includes(data.section)
				? data.section
				: data.administrator
					? 'overview'
					: 'promotions'
		)
	);
	$effect(() => {
		initialPromotion = data.initialPromotion ?? undefined;
		editPromotion = data.editPromotion;
		section = data.initialPromotion
			? 'promotions'
			: [
						'overview',
						'promotions',
						'accounts',
						'subjects',
						'team',
						'configuration',
						'statistics'
				  ].includes(data.section)
				? data.section
				: data.administrator
					? 'overview'
					: 'promotions';
	});
	const tabs = $derived(
		data.administrator
			? [
					{ id: 'overview', name: 'Vue d’ensemble', icon: 'overview' as const },
					{ id: 'promotions', name: 'Promotions', icon: 'promotions' as const },
					{ id: 'accounts', name: 'Comptes', icon: 'accounts' as const },
					{ id: 'subjects', name: 'Matières', icon: 'book' as const },
					{ id: 'team', name: 'Équipe enseignante', icon: 'teacher' as const },
					{ id: 'configuration', name: 'Configuration', icon: 'edit' as const }
				]
			: [
					{ id: 'promotions', name: 'Mes promotions', icon: 'promotions' as const },
					...(canReadStudents
						? [
								{ id: 'accounts', name: 'Mes élèves', icon: 'student' as const },
								{ id: 'statistics', name: 'Mes statistiques', icon: 'overview' as const }
							]
						: [])
				]
	);
	function navigate(value: string): void {
		const url = new URL(window.location.href);
		url.searchParams.set('tab', value);
		url.searchParams.delete('create');
		url.searchParams.delete('promotion');
		url.searchParams.delete('edit');
		if (value === 'promotions' && initialPromotion)
			url.searchParams.set('promotion', String(initialPromotion.id));
		editPromotion = false;
		void goto(resolve(`/dashboard?${url.searchParams}`), {
			replace: true,
			reset: false
		});
	}
</script>

<svelte:head
	><title
		>{data.administrator ? 'Administration' : 'Mes promotions'} — {data.establishmentName}</title
	><meta
		name="description"
		content={`Votre espace de gestion des promotions et des comptes ${data.establishmentName}.`}
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<div class="workspace">
	<aside class="workspace-sidebar">
		<a class="workspace-label" href={resolve('/dashboard')}
			><span class="workspace-symbol"
				><Icon name={data.administrator ? 'overview' : 'student'} size={23} /></span
			><span
				>{data.administrator
					? 'Administration'
					: canReadStudents
						? 'Espace professeur'
						: 'Espace khôlleur'}<small>{data.establishmentName}</small></span
			></a
		>
		<nav aria-label="Navigation de l’espace de gestion">
			{#each tabs as tab (tab.id)}<button
					class:active={section === tab.id}
					aria-current={section === tab.id ? 'page' : undefined}
					onclick={() => navigate(tab.id)}><Icon name={tab.icon} /><span>{tab.name}</span></button
				>{/each}
		</nav>
		<div class="sidebar-note">
			<span class="status-dot"></span>
			<p>
				{data.administrator
					? 'Un espace pour organiser, accompagner et suivre.'
					: 'Vos promotions, vos élèves, au même endroit.'}
			</p>
		</div>
	</aside>
	<div class="workspace-content">
		<header class="workspace-greeting">
			<p class="eyebrow">Votre espace</p>
			<h1>Bonjour {data.user?.first_name ?? data.user?.username}<span class="accent">.</span></h1>
			<p class="muted">
				{data.administrator
					? 'Gardez une vue claire sur la vie de votre établissement.'
					: 'Retrouvez vos élèves et accompagnez leurs progrès.'}
			</p>
		</header>
		{#if section === 'overview' && data.administrator}<Overview />
		{:else if section === 'statistics' && (data.administrator || canReadStudents)}<StatisticsPanel
			/>
		{:else if section === 'subjects' && data.administrator}<SubjectsPanel {initialSubject} />
		{:else if section === 'team' && data.administrator}<TeachingTeamPanel />
		{:else if section === 'configuration' && data.administrator}<SitePanel />
		{:else if section === 'promotions'}<PromotionsPanel
				administrator={data.administrator}
				currentUserId={data.user!.id}
				{canReadStudents}
				{initialPromotion}
				initialEdit={editPromotion}
			/>
		{:else if data.administrator || canReadStudents}<AccountsPanel
				administrator={data.administrator}
				currentUserId={data.user!.id}
				initialCreate={data.create && data.administrator}
			/>{/if}
	</div>
</div>
