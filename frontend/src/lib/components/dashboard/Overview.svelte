<script lang="ts">
	import { onMount } from 'svelte';
	import { read } from '#lib/dashboard';
	import type { DashboardSummary, Page, Promotion } from '#lib/types';
	import ActivityJournal from './ActivityJournal.svelte';
	import Icon from '../Icon.svelte';
	let { onpromotions }: { onpromotions: (promotion?: Promotion) => void } = $props();
	let summary = $state<DashboardSummary | null>(null);
	let promotions = $state<Promotion[]>([]);
	let journalRevision = $state(0);
	let loading = $state(true);
	let message = $state('');
	const chartTitle = $props.id();
	const segments = $derived(
		summary
			? [
					{ label: 'Actifs', value: summary.active_accounts, color: '#3C9875' },
					{ label: 'À activer', value: summary.pending_accounts, color: '#E9AE56' },
					{ label: 'Archivés', value: summary.archived_accounts, color: '#A2ADBA' }
				]
			: []
	);
	async function load(): Promise<void> {
		loading = true;
		message = '';
		try {
			const [counts, active] = await Promise.all([
				read<DashboardSummary>('summary'),
				read<Page<Promotion>>('promotions', { is_active: true, limit: 4 })
			]);
			summary = counts;
			promotions = active.items;
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	}
	onMount(() => {
		void load();
	});
</script>

<div class="section-intro">
	<div>
		<p class="eyebrow">Vue d’ensemble</p>
		<h2 class="title is-3 mb-2">Tout votre établissement, en un regard.</h2>
		<p class="muted">Comptes, promotions et dernières activités.</p>
	</div>
	<button
		class="button is-light"
		disabled={loading}
		onclick={() => {
			journalRevision += 1;
			void load();
		}}><Icon name="restore" />Actualiser</button
	>
</div>
{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
{#if loading && !summary}<p class="loading-state">Chargement des statistiques…</p>{/if}
{#if summary}
	<div class="overview-grid">
		<section class="workspace-panel accounts-chart">
			<div class="panel-heading">
				<h3 class="title is-5 mb-0">Les comptes</h3>
				<span class="mini-label">Tous les rôles</span>
			</div>
			<div class="half-donut">
				<svg viewBox="0 0 240 145" role="img" aria-labelledby={chartTitle}>
					<title id={chartTitle}
						>{summary.total_accounts} comptes : {summary.active_accounts} actifs, {summary.pending_accounts}
						à activer, {summary.archived_accounts} archivés</title
					>
					<path d="M 30 120 A 90 90 0 0 1 210 120" fill="none" stroke="#EDF0F3" stroke-width="20" />
					{#each segments as segment, index (segment.label)}{#if segment.value > 0}<path
								d="M 30 120 A 90 90 0 0 1 210 120"
								fill="none"
								stroke={segment.color}
								stroke-width="20"
								pathLength="100"
								stroke-dasharray={`${(segment.value / summary.total_accounts) * 100} 100`}
								stroke-dashoffset={(-segments
									.slice(0, index)
									.reduce((value, item) => value + item.value, 0) /
									summary.total_accounts) *
									100}
							/>{/if}{/each}
					<text x="120" y="102" text-anchor="middle" class="chart-total"
						>{summary.total_accounts}</text
					><text x="120" y="123" text-anchor="middle" class="chart-caption">comptes au total</text>
				</svg>
			</div>
			<div class="chart-legend">
				{#each segments as segment (segment.label)}<div>
						<span class="legend-dot" style={`background: ${segment.color}`} aria-hidden="true"
						></span><span>{segment.label}</span><strong>{segment.value}</strong><span
							class="muted text-small"
							>{summary.total_accounts
								? Math.round((segment.value / summary.total_accounts) * 100)
								: 0} %</span
						>
					</div>{/each}
			</div>
		</section>
		<section class="workspace-panel promotion-overview">
			<div class="panel-heading">
				<h3 class="title is-5 mb-0">Les promotions</h3>
				<Icon name="promotions" />
			</div>
			<div class="promotion-totals">
				<div><strong>{summary.active_promotions}</strong><span class="muted">actives</span></div>
				<div><strong>{summary.total_promotions}</strong><span class="muted">au total</span></div>
			</div>
			<div class="overview-promotions">
				{#each promotions as promotion (promotion.id)}<button
						onclick={() => onpromotions(promotion)}
						><span class="promotion-dot" style={`background: ${promotion.color}`} aria-hidden="true"
						></span><strong>{promotion.identifier}</strong><span class="muted"
							>{promotion.year}</span
						><span class="muted text-small">{promotion.student_count ?? 0} élèves</span></button
					>{/each}
				{#if promotions.length === 0}<p class="muted">Votre première promotion vous attend.</p>{/if}
			</div>
			<button class="button is-light is-fullwidth mt-4" onclick={() => onpromotions()}
				>Gérer les promotions <Icon name="arrow" /></button
			>
		</section>
	</div>
{/if}
<ActivityJournal revision={journalRevision} />
