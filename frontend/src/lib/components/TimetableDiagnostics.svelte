<script lang="ts">
	import Icon from './Icon.svelte';
	import TimetableWarningEvents from './TimetableWarningEvents.svelte';
	import {
		blockKinds,
		formatTeachingHours,
		type TimetableCatalog,
		type TimetableYear
	} from '#lib/timetable';
	import {
		uniqueWarningTargets,
		warningEventTarget,
		type DiagnosticEntry,
		type WarningEventTarget
	} from '#lib/timetableWarnings';
	let {
		entries,
		year,
		catalog,
		changes = false,
		onopen
	}: {
		entries: DiagnosticEntry[];
		year: TimetableYear;
		catalog: TimetableCatalog;
		changes?: boolean;
		onopen?: (target: WarningEventTarget) => void;
	} = $props();
	function title(entry: DiagnosticEntry): string {
		if (entry.code.startsWith('balance-'))
			return (
				catalog.subjects.find((subject) => subject.id === entry.subject_id)?.name ??
				'Équilibre annuel'
			);
		if (entry.code.startsWith('lunch-')) return 'Repas · ' + entry.code.slice(6);
		if (entry.code.startsWith('availability-')) return 'Disponibilité enseignant';
		if (entry.code.startsWith('teacher-busy-')) return 'Enseignant · autre calendrier';
		return entry.events?.length
			? entry.events
					.map((event) => event.title)
					.filter((value, index, all) => all.indexOf(value) === index)
					.join(' / ')
			: entry.message;
	}
</script>

<div class="diagnostics" aria-live="polite">
	{#if !entries.length}<p class="empty">
			<Icon name="check" /><span
				>{changes ? 'Aucune alerte ajoutée ou supprimée.' : 'Aucun point à vérifier.'}</span
			>
		</p>{/if}
	{#each entries as entry, index (`${entry.code}-${index}`)}
		<article
			class="diagnostic"
			class:critical={entry.severity === 'critical' && entry.change !== 'removed'}
			class:warning={entry.severity === 'warning' && entry.change !== 'removed'}
			class:resolved={entry.change === 'removed'}
		>
			<div class="diagnostic-line">
				<span
					class="status-icon"
					title={entry.change === 'removed'
						? 'Résolue'
						: entry.severity === 'critical'
							? 'Critique'
							: 'À vérifier'}
					><Icon
						name={entry.change === 'removed'
							? 'check'
							: entry.code.startsWith('balance-')
								? 'statistics'
								: entry.code.startsWith('lunch-')
									? 'clock'
									: 'info'}
						size={17}
					/></span
				>
				<strong>{title(entry)}</strong>
				{#if entry.change}<span class="tag change-tag"
						><Icon
							name={entry.change === 'added'
								? 'plus'
								: entry.change === 'removed'
									? 'check'
									: 'arrow'}
							size={11}
						/><span
							>{entry.change === 'added'
								? 'Ajoutée'
								: entry.change === 'removed'
									? 'Résolue'
									: 'Modifiée'}</span
						></span
					>{/if}
				{#if entry.kind}<span class="tag">{blockKinds[entry.kind]}</span>{/if}
				{#if entry.severity === 'critical' && entry.change !== 'removed'}<span
						class="tag severity-tag">Critique</span
					>{/if}
			</div>
			{#if entry.groups}<div class="group-tags">
					<span class="family">{entry.family === 'halves' ? 'Demis' : 'Tiers'}</span
					>{#each entry.groups as group (group.label)}<span class="tag"
							><strong>{group.label}</strong>{#if entry.previous?.groups}{@const old =
									entry.previous.groups.find(
										(item) => item.label === group.label
									)}{#if old && Math.abs(old.hours - group.hours) > 0.000001}<del
										>{formatTeachingHours(old.hours)}</del
									><Icon name="arrow" size={10} />{/if}{/if}{formatTeachingHours(group.hours)}</span
						>{/each}{#each entry.cycles ?? [] as cycle (cycle)}<span class="tag"
							>Cycle {cycle} sem. incomplet</span
						>{/each}
				</div>
			{:else if title(entry) !== entry.message}<p class="diagnostic-message">
					{entry.message}
				</p>{/if}
			{#if entry.events?.length && onopen}<details>
					<summary>Séances concernées</summary><TimetableWarningEvents
						targets={uniqueWarningTargets(
							entry.events.map((event) => warningEventTarget(event, year))
						)}
						{year}
						{catalog}
						{onopen}
					/>
				</details>{/if}
		</article>
	{/each}
</div>

<style>
	.diagnostics {
		display: grid;
		gap: 0.5rem;
		margin-top: 0.85rem;
	}
	.diagnostic {
		--tone: var(--bulma-text);
		--tint: var(--bulma-scheme-main);
		border: 1px solid var(--bulma-border);
		border-left: 3px solid var(--tone);
		border-radius: 0.55rem;
		padding: 0.65rem 0.75rem;
		background: var(--tint);
		font-size: 0.83rem;
	}
	.critical {
		--tone: var(--color-danger);
		--tint: var(--color-danger-soft);
	}
	.warning {
		--tone: var(--color-warning);
		--tint: var(--color-warning-soft);
	}
	.resolved {
		opacity: 0.75;
	}
	.diagnostic-line,
	.group-tags,
	.change-tag,
	.empty {
		display: flex;
		gap: 0.4rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.diagnostic-line > strong {
		flex: 1;
		min-width: 8rem;
	}
	.status-icon {
		display: flex;
		color: var(--tone);
	}
	.tag {
		font-size: 0.69rem;
		height: auto;
		padding: 0.15rem 0.4rem;
		gap: 0.3rem;
	}
	.change-tag,
	.severity-tag {
		color: var(--tone);
		background: color-mix(in srgb, var(--tone) 12%, var(--bulma-scheme-main));
	}
	.group-tags {
		margin: 0.45rem 0 0 1.45rem;
	}
	.family {
		font-size: 0.75rem;
		opacity: 0.7;
	}
	del {
		opacity: 0.6;
	}
	.diagnostic-message {
		margin: 0.35rem 0 0 1.45rem;
		line-height: 1.4;
	}
	details {
		margin: 0.4rem 0 0 1.45rem;
	}
	summary {
		cursor: pointer;
		color: var(--tone);
		font-size: 0.75rem;
	}
	.empty {
		color: var(--bulma-text-weak);
		font-size: 0.85rem;
	}
</style>
