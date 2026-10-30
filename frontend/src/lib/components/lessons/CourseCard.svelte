<script lang="ts">
	import { resolve } from '$app/paths';
	import { colorForeground, lessonTeam, type LessonCard } from '#lib/lessons';
	import Icon from '../Icon.svelte';
	import RoleTag from '../RoleTag.svelte';
	let { lesson, linkStaffProfiles = false }: { lesson: LessonCard; linkStaffProfiles?: boolean } =
		$props();
	const team = $derived(lessonTeam(lesson));
</script>

<article class="course-card" style:--course-color={lesson.color}>
	<div class="card-heading">
		<span
			class="course-symbol"
			style:background={lesson.color}
			style:color={colorForeground(lesson.color)}><Icon name={lesson.icon} size={21} /></span
		>
		<div class="course-identity">
			<p class="course-subject">{lesson.subject_name}</p>
			<h2>
				{#if lesson.can_open}<a href={resolve('/lessons/[id]', { id: String(lesson.id) })}
						>{lesson.title}</a
					>{:else}{lesson.title}{/if}
			</h2>
		</div>
		{#if lesson.can_open}<a
				class="course-open"
				href={resolve('/lessons/[id]', { id: String(lesson.id) })}
				aria-label={`Ouvrir ${lesson.title}`}
				title="Ouvrir le cours"><Icon name="arrow" size={17} /></a
			>{:else}<span class="muted" title="Accès réservé"><Icon name="lock" size={15} /></span>{/if}
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
								userId={linkStaffProfiles ? person.id : undefined}
							/></span
						>{/each}
				</div>{/if}
		{/each}
	</div>
</article>

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
	.course-card:hover {
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
	h2 a {
		color: var(--color-ink);
	}
	.course-open {
		display: grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		flex: 0 0 2rem;
		color: var(--color-primary);
		padding: 0;
		border-radius: 50%;
		background: var(--color-soft);
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
