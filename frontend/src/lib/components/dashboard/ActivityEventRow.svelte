<script lang="ts">
	import type { ActivityEvent, EventType } from '#lib/types';
	import { formatDate } from '#lib/dashboard';
	import {
		eventDetails,
		eventRoles,
		highestRole,
		messageParts,
		roleTransitionLabel
	} from '#lib/activity';
	import RoleTag from '../RoleTag.svelte';
	import PromotionTag from '../PromotionTag.svelte';
	import Icon from '../Icon.svelte';
	let { event, definition }: { event: ActivityEvent; definition?: EventType } = $props();
	const parts = $derived(
		messageParts(definition?.message ?? '{actor} a enregistré une activité concernant {subject}.')
	);
	const details = $derived(eventDetails(event));
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
				{:else if event.promotion_snapshot && event.resource_id}<PromotionTag
						promotion={{ ...event.promotion_snapshot, id: event.resource_id }}
						linked
					/>
				{:else}<span class="muted">Promotion non disponible</span>{/if}
			{/each}
		</p>
		{#if details.length}<ul class="event-details">
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
		color: #40547c;
		background: #edf1fa;
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
