<script lang="ts">
	import type { TimetableNode } from '#lib/timetable';
	let {
		root,
		selected,
		onselect
	}: { root: TimetableNode; selected: string; onselect: (node: TimetableNode) => void } = $props();
	let query = $state('');
	let expanded = $state<string[]>(['promotion']);
	function normalized(value: string): string {
		return value
			.normalize('NFD')
			.replace(/[\u0300-\u036f]/g, '')
			.toLocaleLowerCase('fr');
	}
	function matches(node: TimetableNode): boolean {
		return (
			!query ||
			(node.kind === 'student' && normalized(node.label).includes(normalized(query))) ||
			node.children.some(matches)
		);
	}
	function toggle(key: string): void {
		expanded = expanded.includes(key)
			? expanded.filter((item) => item !== key)
			: [...expanded, key];
	}
</script>

<div class="resource-search">
	<label for="resource-search" class="is-sr-only">Rechercher un élève</label><input
		id="resource-search"
		class="input is-small"
		type="search"
		placeholder="Rechercher un élève…"
		bind:value={query}
	/>
</div>
<nav class="resource-tree" aria-label="Promotion, groupes et élèves">
	{#snippet branch(nodes: TimetableNode[])}
		<ul>
			{#each nodes.filter(matches) as node (node.key)}
				<li>
					<div class="branch-line" class:selected={selected === node.key}>
						{#if node.children.length}<button
								class="disclosure"
								aria-label={`${expanded.includes(node.key) || !!query ? 'Replier' : 'Déplier'} ${node.label}`}
								aria-expanded={expanded.includes(node.key) || !!query}
								onclick={() => toggle(node.key)}
								>{expanded.includes(node.key) || query ? '▾' : '▸'}</button
							>{:else}<span class="disclosure-spacer"></span>{/if}
						<button
							class="resource-label"
							aria-pressed={selected === node.key}
							onclick={() => onselect(node)}
						>
							{#if node.kind === 'student'}<span class="pupil-dot" aria-hidden="true"
								></span>{:else}<svg class="folder" viewBox="0 0 24 24" aria-hidden="true"
									><path
										d="M3 6h6l2 2h10v12H3z"
										fill="none"
										stroke="currentColor"
										stroke-width="1.6"
										stroke-linejoin="round"
									/></svg
								>{/if}
							<span>{node.label}</span>
						</button>
					</div>
					{#if node.children.length && (query || expanded.includes(node.key))}{@render branch(
							node.children
						)}{/if}
				</li>
			{/each}
		</ul>
	{/snippet}
	{@render branch([root])}
	{#if query && !matches(root)}<p class="muted p-4">Aucun élève trouvé.</p>{/if}
</nav>

<style>
	.resource-search {
		padding: 1rem 0.8rem;
		border-bottom: var(--border-thin);
		flex: none;
	}
	.resource-tree {
		overflow: auto;
		padding: 0.65rem 0.35rem 2rem;
	}
	ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	li ul {
		margin-left: 16px;
		padding-left: 5px;
		border-left: 1px solid var(--color-border);
	}
	.branch-line {
		display: flex;
		min-height: 34px;
		align-items: center;
		border-radius: 5px;
	}
	.branch-line:hover {
		background: var(--color-subtle);
	}
	.branch-line.selected {
		background: var(--color-soft);
		color: var(--color-primary);
	}
	.disclosure,
	.resource-label {
		border: 0;
		color: inherit;
		background: none;
		cursor: pointer;
	}
	.disclosure,
	.disclosure-spacer {
		width: 22px;
		flex: none;
		padding: 0;
	}
	.resource-label {
		display: flex;
		align-items: center;
		text-align: left;
		gap: 6px;
		flex: 1;
		min-width: 0;
		font-size: 0.8rem;
		padding: 7px 3px;
		line-height: 1.3;
	}
	.resource-label span:last-child {
		overflow-wrap: anywhere;
	}
	.folder {
		width: 17px;
		height: 17px;
		flex: none;
		color: var(--color-muted);
	}
	.pupil-dot {
		width: 6px;
		height: 6px;
		flex: none;
		border: 1px solid var(--color-muted);
		border-radius: 50%;
		margin: 0 5px;
	}
</style>
