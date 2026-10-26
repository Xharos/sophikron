<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { hasPermission } from '#lib/access';
	import { type LessonDetail } from '#lib/lessons';
	import CourseEditor from '#lib/components/lessons/CourseEditor.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import CourseCard from '#lib/components/lessons/CourseCard.svelte';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let creating = $state(false);
	const linkStaffProfiles = $derived(hasPermission(data.user, 'users.manage'));
	function saved(lesson: LessonDetail): void {
		creating = false;
		void goto(resolve('/lessons/[id]', { id: String(lesson.id) }));
	}
	function catalogueLink(offset: number): `/lessons?${string}` {
		return `/lessons?${new URLSearchParams({ offset: String(offset) })}`;
	}
</script>

<svelte:head
	><title>Cours — {data.establishmentName}</title><meta
		name="description"
		content="Retrouvez les enseignements et les programmes de votre établissement."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="section container dashboard lesson-catalogue">
	<div class="section-intro">
		<div>
			<p class="eyebrow">Apprendre et explorer</p>
			<h1 class="title is-2 mb-3">Les cours</h1>
			<p class="muted">Un espace pour chaque enseignement, un fil pour toute l’année.</p>
		</div>
		{#if data.catalogue.can_create}<button
				class="button is-primary"
				onclick={() => (creating = true)}><Icon name="plus" />Créer un cours</button
			>{/if}
	</div>
	{#if hasPermission(data.user, 'teacher.access') && !data.catalogue.can_create}<p
			class="notification is-warning is-light"
		>
			Aucune matière ne vous est affectée. Un administrateur doit vous en attribuer une pour créer
			un cours.
		</p>{/if}
	<p class="muted text-small mb-4">
		{data.catalogue.total} cours · Les cours réservés s’ouvrent lorsque votre promotion dispose d’un accès.
	</p>
	{#if data.catalogue.items.length}
		<div class="course-grid">
			{#each data.catalogue.items as lesson (lesson.id)}<CourseCard
					{lesson}
					{linkStaffProfiles}
				/>{/each}
		</div>
	{:else}<div class="workspace-panel course-empty">
			<Icon name="book" size={36} />
			<h2 class="title is-4 mt-4">Les premiers cours arrivent bientôt</h2>
			<p class="muted">Les enseignants peuvent créer ici leurs espaces de cours.</p>
		</div>{/if}
	<nav class="course-pagination" aria-label="Pagination des cours">
		{#if data.catalogue.offset > 0}<a
				class="button is-light"
				href={resolve(catalogueLink(Math.max(0, data.catalogue.offset - data.catalogue.limit)))}
				>Précédent</a
			>{/if}{#if data.catalogue.offset + data.catalogue.limit < data.catalogue.total}<a
				class="button is-light"
				href={resolve(catalogueLink(data.catalogue.offset + data.catalogue.limit))}>Suivant</a
			>{/if}
	</nav>
</section>
{#if creating}<CourseEditor onsaved={saved} onclose={() => (creating = false)} />{/if}

<style>
	.section-intro > .button {
		display: inline-flex;
	}
	.course-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
		gap: 1.4rem;
	}
	.course-empty {
		padding: 3rem;
		text-align: center;
	}
	.course-pagination {
		display: flex;
		justify-content: center;
		gap: 1rem;
		margin-top: 2rem;
	}
</style>
