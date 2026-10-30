<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import type { StatisticsPeriod } from '#lib/statistics';
	let { period, revision = 0 }: { period: StatisticsPeriod; revision?: number } = $props();
	type Point = {
		timestamp: string;
		requests: number;
		mean_ms: number | null;
		p95_ms: number | null;
		max_ms: number | null;
		successes: number;
		redirects: number;
		client_errors: number;
		server_errors: number;
		incomplete: number;
		ics_refused: number;
	};
	type Monitoring = {
		categories: {
			key: string;
			label: string;
			requests: number;
			mean_ms: number | null;
			p95_ms: number | null;
			max_ms: number | null;
			server_errors: number;
		}[];
		points: Point[];
		requests: number;
		mean_ms: number | null;
		p95_ms: number | null;
		server_error_rate: number | null;
		dropped_measurements: number;
	};
	const families = [
		{ key: 'successes', label: 'Succès 2xx', color: '#2d8b72' },
		{ key: 'redirects', label: 'Redirections 3xx', color: '#517c91' },
		{ key: 'client_errors', label: 'Refus et erreurs 4xx', color: '#d08a2b' },
		{ key: 'server_errors', label: 'Erreurs serveur 5xx', color: '#d1606a' }
	] as const;
	let data = $state<Monitoring | null>(null),
		ready = $state(false),
		loading = $state(true);
	const latencySeries = [
		{ key: 'mean_ms', label: 'Moyenne', color: '#244bc1' },
		{ key: 'p95_ms', label: 'P95 approximatif', color: '#9c60b6' },
		{ key: 'max_ms', label: 'Maximum', color: '#c65b39' }
	] as const;
	type LatencyKey = (typeof latencySeries)[number]['key'];
	type SeriesKey = LatencyKey | (typeof families)[number]['key'];
	let hidden = $state<SeriesKey[]>([]);
	let message = $state('');
	onMount(() => {
		ready = true;
	});
	$effect(() => {
		const query = new URLSearchParams({ resource: 'monitoring', period, category: 'all' });
		void revision;
		if (!ready) return;
		const controller = new AbortController();
		loading = true;
		message = '';
		void (async () => {
			try {
				const response = await fetch(`${resolve('/statistics')}?${query}`, {
					signal: controller.signal,
					cache: 'no-store'
				});
				const result = await response.json();
				if (!response.ok) throw new Error(result.message || 'Monitoring indisponible.');
				if (!controller.signal.aborted) {
					data = result as Monitoring;
				}
			} catch (cause) {
				if (!controller.signal.aborted) message = (cause as Error).message;
			} finally {
				if (!controller.signal.aborted) loading = false;
			}
		})();
		return () => controller.abort();
	});
	const points = $derived(data?.points ?? []);
	const visibleSeries = $derived(latencySeries.filter((series) => !hidden.includes(series.key)));
	const maxLatency = $derived(
		Math.max(
			1,
			...points.map((point) =>
				Math.max(0, ...visibleSeries.map((series) => point[series.key] ?? 0))
			)
		)
	);
	const visibleFamilies = $derived(families.filter((family) => !hidden.includes(family.key)));
	const maxCount = $derived(
		Math.max(
			1,
			...points.map((point) => visibleFamilies.reduce((sum, family) => sum + point[family.key], 0))
		)
	);
	const barWidth = $derived(974 / Math.max(1, points.length));
	const x = (index: number): number => 58 + (index + 0.5) * barWidth;
	function toggle(key: SeriesKey): void {
		hidden = hidden.includes(key) ? hidden.filter((item) => item !== key) : [...hidden, key];
	}
	function latencyPath(key: LatencyKey): string {
		let connected = false;
		return points
			.map((point, index) => {
				if (point[key] === null) {
					connected = false;
					return '';
				}
				const prefix = connected ? 'L' : 'M';
				connected = true;
				return `${prefix}${x(index)},${180 - (point[key] / maxLatency) * 150}`;
			})
			.join(' ');
	}
	const number = (value: number | null | undefined): string =>
		value === null || value === undefined
			? '—'
			: value.toLocaleString('fr-FR', { maximumFractionDigits: 2 });
	const instant = (value: string): string =>
		new Date(value).toLocaleString('fr-FR', {
			timeZone: 'Europe/Paris',
			day: '2-digit',
			month: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
</script>

<section
	class="workspace-panel api-monitoring mb-5"
	aria-label="Performances API"
	aria-busy={loading}
>
	<header class="monitor-controls">
		<div>
			<p class="eyebrow">Monitoring</p>
			<h3 class="title is-4">Performances API</h3>
		</div>
	</header>
	<p class="help">
		{period === 'day'
			? 'Un point par minute'
			: period === 'week'
				? 'Un point par heure'
				: 'Un point par jour'} · Conservation 31 jours · Mesures enregistrées environ toutes les 30 secondes.
	</p>
	{#if loading}<p class="notification is-light mt-3" role="status">
			Chargement du monitoring… Le reste de la page reste disponible.
		</p>{/if}
	{#if message}<p class="notification is-danger is-light mt-3" role="alert">{message}</p>{/if}
	{#if data && !loading && !message}
		<div class="monitor-kpis mt-4">
			<p><strong>{number(data.requests)}</strong> Requêtes</p>
			<p><strong>{number(data.mean_ms)} ms</strong> Temps moyen</p>
			<p><strong>{number(data.p95_ms)} ms</strong> P95 approximatif</p>
			<p><strong>{number(data.server_error_rate)} %</strong> Erreurs serveur</p>
		</div>
		{#if data.dropped_measurements}<p class="notification is-warning is-light mt-3">
				{number(data.dropped_measurements)} mesures perdues : historique incomplet.
			</p>{/if}
		{#if !data.requests}<p class="notification is-light mt-4">
				Aucune requête enregistrée sur cette période pour ces opérations.
			</p>{/if}
		<div class="monitor-controls mt-4">
			<div class="monitor-legend" role="group" aria-label="Réponses HTTP (axe gauche)">
				{#each families as family (family.key)}
					<button
						type="button"
						class="chart-toggle"
						class:muted-series={hidden.includes(family.key)}
						aria-pressed={!hidden.includes(family.key)}
						onclick={() => toggle(family.key)}
					>
						<span style:color={family.color} aria-hidden="true">●</span>
						{family.label}
					</button>
				{/each}
			</div>
			<div class="monitor-legend" role="group" aria-label="Courbes des durées (axe droit)">
				{#each latencySeries as series (series.key)}
					<button
						type="button"
						class="chart-toggle"
						class:muted-series={hidden.includes(series.key)}
						aria-pressed={!hidden.includes(series.key)}
						onclick={() => toggle(series.key)}
					>
						<span style:color={series.color} aria-hidden="true">●</span>
						{series.label}
					</button>
				{/each}
			</div>
		</div>
		<svg
			class="monitor-plot"
			viewBox="0 0 1100 220"
			role="img"
			aria-label="Nombre de requêtes à gauche et temps de réponse API en millisecondes à droite"
		>
			<text x="58" y="15">Requêtes</text><text x="1032" y="15" text-anchor="end">Durée (ms)</text>
			{#each [0, 0.5, 1] as tick (tick)}
				<line
					x1="58"
					x2="1032"
					y1={180 - tick * 150}
					y2={180 - tick * 150}
					stroke="currentColor"
					opacity=".15"
				/>
				<text x="50" y={185 - tick * 150} text-anchor="end">{number(maxCount * tick)}</text>
				<text x="1040" y={185 - tick * 150}>{number(maxLatency * tick)}</text>
			{/each}
			{#each points as point, index (point.timestamp)}
				{#each visibleFamilies as family, layer (family.key)}
					{@const value = point[family.key]}
					{@const base = visibleFamilies
						.slice(0, layer)
						.reduce((sum, item) => sum + point[item.key], 0)}
					<rect
						class="request-bar"
						data-series={family.key}
						x={58 + index * barWidth}
						y={180 - ((base + value) / maxCount) * 150}
						width={Math.max(0.2, barWidth - 0.4)}
						height={(value / maxCount) * 150}
						fill={family.color}
					>
						<title>{instant(point.timestamp)} · {family.label} : {number(point[family.key])}</title>
					</rect>
				{/each}
			{/each}
			{#each visibleSeries as series (series.key)}
				<path
					data-series={series.key}
					d={latencyPath(series.key)}
					fill="none"
					stroke={series.color}
					stroke-width="2"
				/>
				{#each points as point, index (point.timestamp)}
					{#if point[series.key] !== null && (index === 0 || points[index - 1][series.key] === null) && (index === points.length - 1 || points[index + 1][series.key] === null)}
						<circle
							cx={x(index)}
							cy={180 - ((point[series.key] ?? 0) / maxLatency) * 150}
							r="2.5"
							fill={series.color}
						/>
					{/if}
				{/each}
			{/each}
			{#if points.length}<text x="58" y="210">{instant(points[0].timestamp)}</text><text
					x="1032"
					y="210"
					text-anchor="end"
					>{period === 'day' ? '00:00' : instant(points[points.length - 1].timestamp)}</text
				>{/if}
		</svg>
		<div class="table-container mt-4">
			<table class="table is-fullwidth is-striped is-hoverable">
				<caption class="has-text-left mb-2">Détail par opération</caption>
				<thead
					><tr
						><th scope="col">Opération</th><th scope="col">Requêtes</th><th scope="col"
							>Moyenne (ms)</th
						><th scope="col">P95 approximatif (ms)</th><th scope="col">Maximum (ms)</th><th
							scope="col">Erreurs 5xx</th
						></tr
					></thead
				>
				<tbody>
					{#each data.categories as category (category.key)}
						<tr
							><th scope="row">{category.label}</th><td>{number(category.requests)}</td><td
								>{number(category.mean_ms)}</td
							><td>{number(category.p95_ms)}</td><td>{number(category.max_ms)}</td><td
								>{number(category.server_errors)}</td
							></tr
						>
					{:else}<tr><td colspan="6">Aucune opération enregistrée sur cette période.</td></tr
						>{/each}
				</tbody>
			</table>
		</div>
	{/if}
</section>

<style>
	.api-monitoring {
		min-width: 0;
	}
	.monitor-controls {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
	}
	.monitor-kpis {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 1rem;
	}
	.monitor-kpis strong {
		display: block;
		font-size: 1.6rem;
	}
	.monitor-kpis p {
		font-size: 0.8rem;
	}
	.monitor-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		font-size: 0.8rem;
	}
	.monitor-plot {
		width: 100%;
		height: auto;
		color: var(--color-muted);
		touch-action: pan-y;
	}
	.monitor-plot text {
		fill: currentColor;
		font-size: 12px;
	}
	.monitor-legend button {
		border: 0;
		padding: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.monitor-legend button.muted-series {
		opacity: 0.5;
		text-decoration: line-through;
	}
	@media (max-width: 700px) {
		.monitor-kpis {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
