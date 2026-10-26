<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ActivityEvent, EventType } from '#lib/types';
	import { formatDate } from '#lib/dashboard';
	import {
		eventDetails,
		eventSubjects,
		eventRoles,
		highestRole,
		messageParts,
		roleTransitionLabel
	} from '#lib/activity';
	import RoleTag from '../RoleTag.svelte';
	import PromotionTag from '../PromotionTag.svelte';
	import Icon from '../Icon.svelte';
	import SubjectTag from '../SubjectTag.svelte';
	let { event, definition }: { event: ActivityEvent; definition?: EventType } = $props();
	const parts = $derived(
		messageParts(definition?.message ?? '{actor} a enregistré une activité concernant {subject}.')
	);
	const details = $derived(eventDetails(event));
	const addedSubjects = $derived(
		event.event_type === 'user.subjects_updated' ? eventSubjects(event.data.added) : []
	);
	const removedSubjects = $derived(
		event.event_type === 'user.subjects_updated' ? eventSubjects(event.data.removed) : []
	);
	const matter = $derived(
		event.event_type.startsWith('subject.') ? eventSubjects([event.data.subject])[0] : undefined
	);
	const previousMatter = $derived(eventSubjects([event.data.previous])[0]);
	const previous = $derived(eventRoles(event.data.previous_roles));
	const next = $derived(eventRoles(event.data.roles));
	const subjectName = $derived(event.subject_label ?? 'Compte non disponible');
	const subjectId = $derived(
		event.subject_profile_available ? (event.subject_user_id ?? undefined) : undefined
	);
</script>

<article class="event-row" data-event-id={event.id} data-event-type={event.event_type}>
	<span class="event-symbol" title={definition?.label ?? event.event_type}
		><Icon name={definition?.icon ?? 'clock'} size={17} /></span
	>
	<div class="event-body">
		<p class="event-message">
			{#each parts as part, index (index)}
				{#if part.kind === 'text'}{part.text}
				{:else if part.kind === 'actor'}<RoleTag
						role={event.actor_role}
						label={event.actor_label ??
							(event.actor_user_id ? 'Compte non disponible' : 'Le système')}
						userId={event.actor_profile_available ? (event.actor_user_id ?? undefined) : undefined}
						historical
					/>
				{:else if part.kind === 'subject'}<RoleTag
						role={event.subject_role}
						label={subjectName}
						userId={subjectId}
						historical
					/>
				{:else if part.kind === 'roles'}
					<span class="role-transition"
						><RoleTag
							role={highestRole(previous)}
							label={roleTransitionLabel(subjectName, previous)}
							userId={subjectId}
							historical
						/><span aria-label="devient">→</span><RoleTag
							role={highestRole(next)}
							label={roleTransitionLabel(subjectName, next)}
							userId={subjectId}
							historical
						/></span
					>
				{:else if part.kind === 'lesson' && event.resource_id}
					<a
						class="lesson-event-link"
						href={resolve(
							`/lessons/[id]#${typeof event.data.element_id === 'number' && event.event_type !== 'lesson.element_deleted' ? `element-${event.data.element_id}` : ''}`,
							{ id: String(event.resource_id) }
						)}><Icon name="book" size={14} />{event.resource_label ?? 'Cours'}</a
					>
				{:else if event.promotion_snapshot && event.resource_id}<PromotionTag
						promotion={{ ...event.promotion_snapshot, id: event.resource_id }}
						linked
					/>
				{:else}<span class="muted">Promotion non disponible</span>{/if}
			{/each}
		</p>
		{#if details.length || addedSubjects.length || removedSubjects.length || matter}<ul
				class="event-details"
			>
				{#if addedSubjects.length}<li class="subject-changes">
						<span>Matières attribuées :</span
						>{#each addedSubjects as subject (subject.id)}<SubjectTag {subject} />{/each}
					</li>{/if}
				{#if removedSubjects.length}<li class="subject-changes">
						<span>Matières retirées :</span
						>{#each removedSubjects as subject (subject.id)}<SubjectTag {subject} />{/each}
					</li>{/if}
				{#if matter}<li class="subject-changes">
						<span>Matière :</span>{#if previousMatter}<SubjectTag subject={previousMatter} /><span
								aria-label="devient">→</span
							>{/if}<SubjectTag subject={matter} />
					</li>{/if}
				{#each details as detail (detail)}<li>{detail}</li>{/each}
			</ul>{/if}
	</div>
	<time
		datetime={event.occurred_at}
		title={new Date(event.occurred_at).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' })}
		>{formatDate(event.occurred_at)}</time
	>
</article>

<style>
	.lesson-event-link {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.1rem 0.5rem;
		border-radius: 0.4rem;
		background: var(--color-soft);
		font-size: 0.8rem;
		vertical-align: middle;
	}
	.event-row {
		grid-template-columns: 34px minmax(0, 1fr) auto;
		align-items: start;
		padding: 1.1rem 0;
	}
	.event-symbol {
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: 10px;
		color: var(--color-primary);
		background: var(--color-soft);
	}
	.event-body {
		min-width: 0;
	}
	.event-message {
		line-height: 2.2;
	}
	.event-details {
		color: var(--color-muted);
		font-size: 0.77rem;
		margin: 0.4rem 0 0;
		list-style: none;
		padding: 0;
		line-height: 1.7;
	}
	.subject-changes {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-bottom: 0.3rem;
	}
	.role-transition {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		max-width: 100%;
	}
	time {
		padding-top: 0.45rem;
	}
	@media (max-width: 700px) {
		.event-row {
			grid-template-columns: 30px minmax(0, 1fr);
		}
		time {
			grid-column: 2;
			padding-top: 0;
		}
	}
</style>
