<script lang="ts">
	import { chartMaximum, linePoints, pointBounds, type ChartSeries } from '#lib/statistics';
	import { themeAccent } from '#lib/colors';
	let {
		title,
		kind = 'line',
		series,
		labels = [],
		details = labels,
		center = '',
		format = (value: number) => value.toLocaleString('fr-FR')
	}: {
		title: string;
		kind?: 'line' | 'donut' | 'bars' | 'stacked';
		series: ChartSeries[];
		labels?: string[];
		details?: string[];
		center?: string;
		format?: (value: number) => string;
	} = $props();
	const chartId = $props.id();
	let hidden = $state<string[]>([]);
	let selected = $state(0);
	$effect(() => {
		void labels;
		selected = Math.max(0, labels.length - 1);
	});
	const displaySeries = $derived(
		series.map((item) => ({ ...item, color: themeAccent(item.color) }))
	);
	const visible = $derived(displaySeries.filter((item) => !hidden.includes(item.key)));
	const maximum = $derived(
		kind === 'stacked'
			? chartMaximum([
					{
						key: 'all',
						label: '',
						color: '',
						values: labels.map((_, i) =>
							visible.reduce((sum, item) => sum + (item.values[i] || 0), 0)
						)
					}
				])
			: chartMaximum(visible)
	);
	const total = $derived(visible.reduce((sum, item) => sum + (item.values[0] || 0), 0));
	const hasValues = $derived(visible.some((item) => item.values.some((value) => value > 0)));
	function toggle(key: string): void {
		hidden = hidden.includes(key) ? hidden.filter((item) => item !== key) : [...hidden, key];
	}
	function offset(index: number): number {
		return visible.slice(0, index).reduce((sum, item) => sum + (item.values[0] || 0), 0);
	}
</script>

<div class="stat-chart" data-chart-kind={kind}>
	<div class="chart-legend" role="group" aria-label={`Séries : ${title}`}>
		{#each displaySeries as item (item.key)}<button
				type="button"
				class:muted-series={hidden.includes(item.key)}
				aria-pressed={!hidden.includes(item.key)}
				onclick={() => toggle(item.key)}
			>
				<span class="legend-dot" style:background={item.color}></span>{item.label}
			</button>{/each}
	</div>
	{#if !visible.length}<p class="chart-empty" role="status">
			{series.length
				? 'Toutes les séries sont masquées. Cliquez sur la légende pour les réafficher.'
				: 'Aucune donnée disponible pour ce graphique.'}
		</p>
	{:else if kind === 'line'}
		<svg viewBox="0 0 530 218" role="img" aria-labelledby={chartId}>
			<title id={chartId}
				>{title}. {hasValues
					? 'Sélectionnez un point pour consulter les valeurs.'
					: 'Aucune activité sur cette période.'}</title
			>
			{#each [0, 0.5, 1] as tick (tick)}<line
					x1="44"
					x2="510"
					y1={184 - tick * 160}
					y2={184 - tick * 160}
					class="grid-line"
				/><text x="36" y={188 - tick * 160} text-anchor="end">{format(maximum * tick)}</text>{/each}
			{#each visible as item (item.key)}<polyline
					points={linePoints(item.values, maximum)}
					fill="none"
					stroke={item.color}
					stroke-width="2.8"
					stroke-linejoin="round"
					stroke-linecap="round"
					vector-effect="non-scaling-stroke"
				/><circle
					cx={44 + (selected / Math.max(1, labels.length - 1)) * 466}
					cy={184 - ((item.values[selected] || 0) / maximum) * 160}
					r="3.5"
					fill={item.color}
				/>{/each}
			{#each labels as label, index (index)}
				{@const x = 44 + (index / Math.max(1, labels.length - 1)) * 466}
				{#if index === 0 || index === labels.length - 1 || index === Math.floor(labels.length / 2)}<text
						{x}
						y="209"
						text-anchor={index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle'}
						>{label}</text
					>{/if}
				<rect
					x={pointBounds(index, labels.length).x}
					y="20"
					width={pointBounds(index, labels.length).width}
					height="168"
					fill="transparent"
					role="button"
					tabindex="0"
					aria-label={`${details[index]} : ${visible.map((item) => `${item.label} ${format(item.values[index] || 0)}`).join(', ')}`}
					onpointerenter={() => (selected = index)}
					onfocus={() => (selected = index)}
					onclick={() => (selected = index)}
					onkeydown={(event) => {
						if (event.key === 'Enter' || event.key === ' ') {
							event.preventDefault();
							selected = index;
						}
					}}
				/>
			{/each}
			<line
				x1={44 + (selected / Math.max(1, labels.length - 1)) * 466}
				x2={44 + (selected / Math.max(1, labels.length - 1)) * 466}
				y1="24"
				y2="184"
				class="selection-line"
			/>
		</svg>
		<div class="chart-tooltip" aria-live="polite">
			<strong>{details[selected] || ''}</strong>{#each visible as item (item.key)}<span
					><i style:background={item.color}></i>{item.label}
					<b>{format(item.values[selected] || 0)}</b></span
				>{/each}
		</div>
	{:else if kind === 'donut'}
		<div class="donut-layout">
			<svg viewBox="0 0 220 220" role="img" aria-labelledby={chartId}>
				<title id={chartId}
					>{title} : {visible
						.map((item) => `${item.label} ${format(item.values[0] || 0)}`)
						.join(', ')}</title
				>
				<circle
					cx="110"
					cy="110"
					r="78"
					fill="none"
					stroke="var(--color-paper)"
					stroke-width="24"
				/>
				{#if total > 0}{#each visible as item, index (item.key)}<circle
							cx="110"
							cy="110"
							r="78"
							fill="none"
							stroke={item.color}
							stroke-width="24"
							pathLength="100"
							stroke-dasharray={`${(item.values[0] / total) * 100} 100`}
							stroke-dashoffset={(-offset(index) / total) * 100}
							transform="rotate(-90 110 110)"
							><title>{item.label} : {format(item.values[0])}</title></circle
						>{/each}{/if}
				<text x="110" y="108" text-anchor="middle" class="donut-value">{format(total)}</text><text
					x="110"
					y="130"
					text-anchor="middle">{center || 'Total visible'}</text
				>
			</svg>
			<ul class="chart-values">
				{#each visible as item (item.key)}<li>
						<span><i style:background={item.color}></i>{item.label}</span><b
							>{format(item.values[0] || 0)}</b
						>
					</li>{/each}
			</ul>
		</div>
	{:else}
		<div class="bar-list">
			{#each labels as label, index (index)}<div class="bar-row">
					<span class="bar-label" title={label}>{label}</span>
					<div class="bar-track">
						{#each visible as item (item.key)}<span
								class="bar-fill"
								style:background={item.color}
								style:width={`${((item.values[index] || 0) / maximum) * 100}%`}
								title={`${item.label} : ${format(item.values[index] || 0)}`}
							></span>{/each}
					</div>
					<b>{format(visible.reduce((sum, item) => sum + (item.values[index] || 0), 0))}</b>
				</div>{/each}
		</div>
	{/if}
	{#if visible.length && !hasValues}<p class="chart-note">
			Aucune donnée pour les séries affichées.
		</p>{/if}
	<details class="chart-table">
		<summary>Afficher les données du graphique</summary>
		<div class="table-container">
			<table class="table is-fullwidth is-narrow">
				<caption class="is-sr-only">{title}</caption><thead
					><tr
						><th scope="col">{kind === 'donut' ? 'Série' : 'Période ou catégorie'}</th
						>{#if kind === 'donut'}<th scope="col">Valeur</th
							>{:else}{#each visible as item (item.key)}<th scope="col">{item.label}</th
								>{/each}{/if}</tr
					></thead
				><tbody>
					{#if kind === 'donut'}{#each visible as item (item.key)}<tr
								><th scope="row">{item.label}</th><td>{format(item.values[0])}</td></tr
							>{/each}{:else}{#each labels as label, index (index)}<tr
								><th scope="row">{details[index] || label}</th>{#each visible as item (item.key)}<td
										>{format(item.values[index] || 0)}</td
									>{/each}</tr
							>{/each}{/if}
				</tbody>
			</table>
		</div>
	</details>
</div>

<style>
	.stat-chart {
		width: 100%;
		min-width: 0;
	}
	.chart-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem 0.8rem;
		margin-bottom: 0.8rem;
	}
	.chart-legend button {
		border: 0;
		background: transparent;
		padding: 0.25rem 0;
		color: var(--color-ink);
		font: inherit;
		font-size: 0.72rem;
		display: flex;
		align-items: center;
		gap: 0.35rem;
		cursor: pointer;
	}
	.chart-legend button:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
		border-radius: 3px;
	}
	.chart-legend .muted-series {
		opacity: 0.45;
		text-decoration: line-through;
	}
	.legend-dot,
	i {
		display: inline-block;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	svg {
		display: block;
		width: 100%;
		overflow: visible;
	}
	svg text {
		font-family: var(--font-body);
		font-size: 12px;
		fill: var(--color-muted);
	}
	.grid-line {
		stroke: var(--color-border);
		stroke-dasharray: 3 5;
	}
	.selection-line {
		stroke: var(--color-muted);
		stroke-dasharray: 4 4;
		pointer-events: none;
		opacity: 0.45;
	}
	.chart-tooltip {
		background: var(--color-paper);
		border-radius: 0.5rem;
		padding: 0.6rem 0.75rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem 0.8rem;
		font-size: 0.7rem;
		min-height: 3.5rem;
	}
	.chart-tooltip strong {
		width: 100%;
	}
	.chart-tooltip span {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.donut-layout {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		flex-wrap: wrap;
	}
	.donut-layout svg {
		max-width: 180px;
		margin: 0 auto;
	}
	svg .donut-value {
		font-size: 23px;
		font-weight: 700;
		fill: var(--color-ink);
	}
	.chart-values {
		list-style: none;
		flex: 1;
		min-width: 120px;
		font-size: 0.75rem;
	}
	.chart-values li {
		display: flex;
		justify-content: space-between;
		gap: 0.7rem;
		padding: 0.35rem 0;
	}
	.chart-values span {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.bar-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		margin: 0.8rem 0;
	}
	.bar-row {
		display: grid;
		grid-template-columns: minmax(60px, 1.1fr) minmax(40px, 1.5fr) auto;
		gap: 0.65rem;
		align-items: center;
		font-size: 0.73rem;
	}
	.bar-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.bar-track {
		display: flex;
		min-height: 0.65rem;
		background: var(--color-paper);
		border-radius: 5px;
		overflow: hidden;
	}
	.bar-fill {
		height: 0.65rem;
		transition: width 0.18s;
	}
	.chart-empty {
		min-height: 150px;
		display: grid;
		place-items: center;
		color: var(--color-muted);
		font-size: 0.8rem;
		text-align: center;
		padding: 1rem;
	}
	.chart-note {
		font-size: 0.72rem;
		color: var(--color-muted);
		margin-top: 0.5rem;
	}
	.chart-table {
		font-size: 0.7rem;
		margin-top: 0.6rem;
		color: var(--color-muted);
	}
	.chart-table summary {
		cursor: pointer;
		padding: 0.25rem 0;
	}
	.chart-table table {
		font-size: 0.7rem;
		margin-top: 0.5rem;
	}
	@media (prefers-reduced-motion: reduce) {
		.bar-fill {
			transition: none;
		}
	}
</style>
