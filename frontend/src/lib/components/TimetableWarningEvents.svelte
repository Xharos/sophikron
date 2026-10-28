<script lang="ts">
	import RoleTag from './RoleTag.svelte';
	import { blockKinds, type TimetableCatalog, type TimetableYear } from '#lib/timetable';
	import {
		warningEventWhen,
		warningTeachingRole,
		type WarningEventTarget
	} from '#lib/timetableWarnings';
	let {
		targets,
		year,
		catalog,
		onopen
	}: {
		targets: WarningEventTarget[];
		year: TimetableYear;
		catalog: TimetableCatalog;
		onopen: (target: WarningEventTarget) => void;
	} = $props();
</script>

<ul class="warning-events">
	{#each targets as target (`${target.event.series_id}-${target.event.source_date}`)}
		{@const event = target.event}
		{@const teacher = catalog.teachers.find((item) => item.id === event.teacher_id)}
		{@const roles = event.teacher_roles ?? teacher?.roles ?? []}
		{@const color =
			catalog.subjects.find((item) => item.id === event.subject_id)?.color ?? '#64748B'}
		<li>
			<button
				type="button"
				class="warning-event-link"
				onclick={() => onopen(target)}
				aria-label={`${catalog.administrator ? 'Modifier' : 'Consulter'} ${event.title} · ${warningEventWhen(target, year)}`}
			>
				<strong>{event.title}</strong><span>{warningEventWhen(target, year)}</span>
			</button>
			<div class="warning-event-tags">
				<span class="tag">{blockKinds[event.kind]}</span>
				{#if event.teacher_id !== null && (event.teacher || teacher?.name)}
					<RoleTag
						role={warningTeachingRole(event.kind, roles)}
						label={event.teacher || teacher?.name}
						userId={catalog.administrator ? event.teacher_id : undefined}
						{color}
					/>
				{/if}
			</div>
		</li>
	{/each}
</ul>

<style>
	.warning-events {
		display: grid;
		gap: 0.7rem;
		margin-top: 0.7rem;
	}
	.warning-event-link {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		text-align: left;
		border: 0;
		padding: 0;
		color: var(--color-primary);
		background: none;
		font: inherit;
		cursor: pointer;
		text-decoration: underline;
		text-underline-offset: 0.15em;
	}
	.warning-event-link span {
		font-size: 0.8rem;
	}
	.warning-event-tags {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		margin-top: 0.35rem;
	}
	.warning-event-link:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
	}
</style>
