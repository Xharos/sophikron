<script lang="ts">
	import { resolve } from '$app/paths';
	import { colorForeground, lessonTeam, type LessonCard } from '#lib/lessons';
	import Icon from '../Icon.svelte';
	import RoleTag from '../RoleTag.svelte';
	let { lesson }: { lesson: LessonCard } = $props();
	const team = $derived(lessonTeam(lesson));
	const titleId = $props.id();
</script>

{#snippet content()}
	<div class="card-heading">
		<span
			class="course-symbol"
			style:background={lesson.color}
			style:color={colorForeground(lesson.color)}><Icon name={lesson.icon} size={21} /></span
		>
		<div class="course-identity">
			<p class="course-subject">{lesson.subject_name}</p>
			<h2 id={titleId}>{lesson.title}</h2>
		</div>
		{#if !lesson.can_open}<span class="muted" title="Accès réservé"
				><Icon name="lock" size={15} /></span
			>{/if}
	</div>
	<p class="course-description" title={lesson.description}>{lesson.description}</p>
	<div class="course-team">
		{#each [{ label: 'Professeurs', people: team.teachers }, { label: 'Khôlleurs', people: team.kholleurs }] as group (group.label)}
			{#if group.people.length}<div class="team-line" role="group" aria-label={group.label}>
					{#each group.people as person (person.id)}<span
							title={person.id === lesson.responsible.id ? 'Responsable du cours' : undefined}
							><RoleTag
								role={person.role === 'teacher' || person.role === 'kholleur' ? person.role : null}
								label={person.label}
							/></span
						>{/each}
				</div>{/if}
		{/each}
	</div>
{/snippet}

{#if lesson.can_open}
	<a
		class="course-card"
		style:--course-color={lesson.color}
		href={resolve('/lessons/[id]', { id: String(lesson.id) })}
		aria-labelledby={titleId}
	>
		{@render content()}
	</a>
{:else}
	<article class="course-card" style:--course-color={lesson.color}>
		{@render content()}
	</article>
{/if}

<style>
	.course-card {
		min-width: 0;
		padding: 1.15rem;
		border: var(--border-thin);
		border-top: 3px solid var(--course-color);
		border-radius: 1rem;
		background: var(--color-surface);
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		transition: box-shadow 150ms ease;
	}
	a.course-card:hover {
		box-shadow: var(--shadow-panel);
	}
	.card-heading {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}
	.course-symbol {
		width: 42px;
		height: 42px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border-radius: 0.8rem;
	}
	.course-identity {
		min-width: 0;
		flex: 1;
	}
	.course-subject {
		font-size: 0.7rem;
		color: var(--color-muted);
		margin-bottom: 0.15rem;
	}
	h2 {
		font-size: 1.1rem;
		font-weight: 650;
		line-height: 1.25;
		overflow-wrap: anywhere;
	}
	a.course-card {
		color: var(--color-ink);
		text-decoration: none;
	}
	a.course-card:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
	}
	.course-description {
		color: var(--color-muted);
		font-size: 0.85rem;
		line-height: 1.55;
		overflow-wrap: anywhere;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
	}
	.course-team {
		display: grid;
		gap: 0.4rem;
		padding-top: 0.7rem;
		border-top: var(--border-thin);
		margin-top: auto;
	}
	.team-line {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		align-items: center;
	}
</style>
