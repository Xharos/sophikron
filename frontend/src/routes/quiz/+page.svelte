<script lang="ts">
	import { resolve } from '$app/paths';
	import Icon from '#lib/components/Icon.svelte';
	import { colorForeground } from '#lib/lessons';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head>
	<title>Quiz · Sophikron</title>
	<meta name="description" content="Banque de fiches de questions par matière." />
</svelte:head>

<section class="section">
	<div class="container">
		<h1 class="title">Quiz</h1>
		<p class="subtitle">Fiches de questions par matière</p>
		{#if data.subjects.length}
			<div class="promotion-grid">
				{#each data.subjects as subject (subject.id)}
					<a
						class="promotion-card subject-card"
						style:--promotion-color={subject.color}
						style:--promotion-ink={colorForeground(subject.color)}
						href={resolve('/quiz/[subjectId]', { subjectId: String(subject.id) })}
					>
						<span class="promotion-card-top">
							<span class="card-emblem" aria-hidden="true"
								><Icon name={subject.icon} size={22} /></span
							>
							<Icon name="open" size={14} />
						</span>
						<strong>{subject.name}</strong>
						<span class="muted text-small">
							{subject.total}
							{subject.total === 1 ? 'fiche' : 'fiches'}
							· {subject.total - subject.archived} visibles · {subject.archived} archivées
						</span>
						{#if !subject.is_active}<span class="muted text-small">Matière archivée</span>{/if}
					</a>
				{/each}
			</div>
		{:else}
			<p>Aucune matière configurée.</p>
		{/if}
	</div>
</section>

<style>
	a.subject-card,
	a.subject-card:hover,
	a.subject-card:focus-visible {
		text-decoration: none;
	}
</style>
