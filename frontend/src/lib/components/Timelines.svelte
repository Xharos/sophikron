<script lang="ts">
	import { onMount } from 'svelte';
	import {
		eventLabels,
		calendarLegend,
		parisDay,
		timelineProgress,
		timelineEventEnd,
		timelineStats,
		timelineMonths,
		type PublicSite,
		type TimelineEvent
	} from '#lib/site';
	import { lessonDate } from '#lib/lessons';
	import Icon from './Icon.svelte';
	let { site }: { site: PublicSite } = $props();
	let today = $state('');
	onMount(() => {
		today = parisDay();
		const timer = window.setInterval(() => {
			today = parisDay();
		}, 60000);
		return () => window.clearInterval(timer);
	});
	const day = $derived(today || site.today);
	const legend = $derived(calendarLegend(site.events, site.settings.holiday_color));
	function eventDescription(event: TimelineEvent): string {
		return (
			event.name +
			' · ' +
			eventLabels[event.kind] +
			' · ' +
			lessonDate(event.starts_on) +
			(event.ends_on === event.starts_on ? '' : ' — ' + lessonDate(event.ends_on))
		);
	}
</script>

{#if site.timelines.length}
	<section class="section container calendar-overview" aria-label="Calendrier de l’année">
		{#each site.timelines as bar (bar.id)}
			{@const stats = timelineStats(bar, site.events, day)}
			<article class="timeline-card" style:--bar-color={bar.color}>
				<header>
					<h2 class="title is-6 mb-0">{bar.name}</h2>
					<details class="timeline-info">
						<summary aria-label={'Informations sur ' + bar.name}
							><span>{Math.floor(stats.progress)} %</span><Icon name="info" size={16} /></summary
						>
						<div class="timeline-information">
							<strong>{bar.name}</strong>
							<p>{lessonDate(bar.starts_on)} — {lessonDate(bar.ends_on)}</p>
							<p>
								<strong>{Math.floor(stats.progress)} %</strong> écoulés · {stats.remainingDays} jours
								calendaires restants sur {stats.totalDays}
							</p>
							<p>
								<strong>{stats.remainingWorkingDays} jours de cours restants</strong> sur {stats.totalWorkingDays}
							</p>
							<p class="help">
								Jour courant inclus. Du lundi au vendredi, hors vacances de cette barre. Les autres
								événements ne retirent pas de jours de cours.
							</p>
						</div>
					</details>
				</header>
				<div class="timeline-rail" role="group" aria-label={'Calendrier de ' + bar.name}>
					<div class="timeline-months" aria-hidden="true">
						{#each timelineMonths(bar.starts_on, bar.ends_on) as month (month.key)}
							<span style:width={month.width + '%'} title={month.title}
								><span>{month.label}</span></span
							>
						{/each}
					</div>
					<div class="timeline-elapsed" style:width={stats.progress + '%'} aria-hidden="true"></div>
					{#each site.events.filter( (event) => event.timeline_ids.includes(bar.id) ) as event (event.id)}
						<button
							type="button"
							class="timeline-event calendar-tip"
							class:tip-right={timelineProgress(bar.starts_on, bar.ends_on, event.starts_on) > 50}
							aria-label={eventDescription(event)}
							style:left={timelineProgress(bar.starts_on, bar.ends_on, event.starts_on) + '%'}
							style:width={timelineEventEnd(bar.starts_on, bar.ends_on, event.ends_on) -
								timelineProgress(bar.starts_on, bar.ends_on, event.starts_on) +
								'%'}
							style:--event-color={event.kind === 'holiday'
								? site.settings.holiday_color
								: event.color}
						>
							<span class="tip" aria-hidden="true">{eventDescription(event)}</span>
						</button>
					{/each}
					{#if day >= bar.starts_on && day <= bar.ends_on}
						<button
							type="button"
							class="today-cursor calendar-tip"
							class:tip-right={stats.progress > 50}
							style:left={stats.progress + '%'}
							aria-label={'Aujourd’hui, le ' + lessonDate(day)}
						>
							<span class="tip" aria-hidden="true">Aujourd’hui, le {lessonDate(day)}</span>
						</button>
					{/if}
				</div>
			</article>
		{/each}
		<div class="calendar-legend" role="region" aria-label="Légende commune des calendriers">
			<button type="button" class="legend-item" title={'Aujourd’hui, le ' + lessonDate(day)}
				><i class="today-dot"></i>Aujourd’hui</button
			>
			{#each legend as entry (entry.key)}
				<button
					type="button"
					class="legend-item"
					title={entry.event ? eventDescription(entry.event) : 'Vacances scolaires'}
					aria-label={entry.event ? eventDescription(entry.event) : 'Vacances scolaires'}
					><i style:background={entry.color}></i>{entry.label}</button
				>
			{/each}
		</div>
	</section>
{/if}

<style>
	.calendar-overview {
		padding-top: 1.5rem;
		padding-bottom: 1rem;
	}
	.timeline-card + .timeline-card {
		margin-top: 1rem;
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 0.5rem;
	}
	h2 {
		border-left: 3px solid var(--bar-color);
		padding-left: 0.6rem;
	}
	.timeline-info {
		position: relative;
		font-size: 0.8rem;
	}
	summary {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		cursor: pointer;
		color: var(--color-muted);
	}
	summary::-webkit-details-marker {
		display: none;
	}
	.timeline-information {
		position: absolute;
		right: 0;
		top: 1.8rem;
		z-index: 12;
		width: min(320px, 80vw);
		padding: 1rem;
		background: var(--color-paper);
		border: var(--border-thin);
		border-radius: 0.6rem;
		box-shadow: 0 8px 24px #0002;
	}
	.timeline-information p {
		margin-top: 0.5rem;
	}
	.timeline-rail {
		position: relative;
		height: 34px;
		background: color-mix(in srgb, var(--bar-color) 8%, var(--color-paper));
		border-radius: 0.35rem;
	}
	.timeline-months {
		display: flex;
		position: absolute;
		inset: 0;
		pointer-events: none;
		z-index: 3;
	}
	.timeline-months > span {
		display: flex;
		align-items: center;
		justify-content: center;
		min-width: 0;
		border-left: 1px solid var(--color-border);
		font-size: 0.7rem;
		color: var(--color-ink);
	}
	.timeline-months > span:first-child {
		border-left: none;
	}
	.timeline-months > span > span {
		background: var(--color-paper);
		padding: 0.1rem 0.2rem;
		border-radius: 3px;
		overflow: hidden;
		text-overflow: clip;
		white-space: nowrap;
	}
	.timeline-elapsed {
		position: absolute;
		inset: 0 auto 0 0;
		background: color-mix(in srgb, var(--bar-color) 14%, transparent);
		border-radius: inherit;
		pointer-events: none;
	}
	.timeline-event {
		position: absolute;
		top: 0;
		bottom: 0;
		min-width: 3px;
		padding: 0;
		border: 1px solid var(--event-color);
		outline: 1px solid var(--color-muted);
		border-radius: 3px;
		background: color-mix(in srgb, var(--event-color) 42%, transparent);
		cursor: help;
	}
	.today-cursor {
		position: absolute;
		z-index: 5;
		top: -4px;
		bottom: -4px;
		width: 3px;
		transform: translateX(-1px);
		background: var(--color-today);
		padding: 0;
		border: 0;
		cursor: help;
	}
	.today-cursor::before {
		content: '';
		position: absolute;
		top: -3px;
		left: -3px;
		border: 4px solid transparent;
		border-top-color: var(--color-today);
	}
	.calendar-tip:hover,
	.calendar-tip:focus {
		z-index: 8;
		outline: 2px solid var(--color-primary);
		outline-offset: 2px;
	}
	.tip {
		visibility: hidden;
		position: absolute;
		bottom: calc(100% + 10px);
		left: 0;
		width: max-content;
		max-width: min(220px, 42vw);
		text-align: left;
		font-size: 0.75rem;
		line-height: 1.4;
		color: #fff;
		background: #1e293b;
		padding: 0.45rem 0.6rem;
		border-radius: 0.35rem;
		pointer-events: none;
	}
	.calendar-tip:hover .tip,
	.calendar-tip:focus .tip {
		visibility: visible;
	}
	.tip-right .tip {
		left: auto;
		right: 0;
	}
	.calendar-legend {
		display: flex;
		align-items: center;
		gap: 1rem;
		overflow-x: auto;
		padding: 0.7rem 0 0.25rem;
		font-size: 0.73rem;
		white-space: nowrap;
	}
	.legend-item {
		border: 0;
		padding: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		cursor: help;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	.legend-item i {
		width: 8px;
		height: 8px;
		border-radius: 2px;
		flex-shrink: 0;
		box-shadow: 0 0 0 1px var(--color-muted);
	}
	.today-dot {
		background: var(--color-today);
	}
	@media (max-width: 600px) {
		.timeline-months > span {
			font-size: 0.6rem;
		}
	}
</style>
