<script lang="ts">
	import { groupIdentifier } from '#lib/groups';
	import type { GroupAssignment, PartitionKind } from '#lib/groups';
	let { assignments = [], promotionId }: { assignments?: GroupAssignment[]; promotionId: number } =
		$props();
	const labels: Record<PartitionKind, string> = {
		halves: 'Demi-groupe',
		thirds: 'Tiers de groupe',
		kholles: 'Groupe de khôlle'
	};
	const kinds: PartitionKind[] = ['halves', 'thirds', 'kholles'];
	const tags = $derived(
		kinds.flatMap((kind) => {
			const assignment = assignments.find(
				(item) => item.promotion_id === promotionId && item.kind === kind
			);
			return assignment ? [assignment] : [];
		})
	);
</script>

{#if tags.length}<span class="group-tags">
		{#each tags as assignment (assignment.kind)}
			<span
				class={`tag is-rounded group-tag-${assignment.kind}`}
				title={`${labels[assignment.kind]} ${groupIdentifier(assignment.kind, assignment.number)}`}
				aria-label={`${labels[assignment.kind]} ${groupIdentifier(assignment.kind, assignment.number)}`}
			>
				{groupIdentifier(assignment.kind, assignment.number)}
			</span>
		{/each}
	</span>{/if}

<style>
	.group-tags {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem;
	}
	.group-tags .tag {
		font-weight: 650;
		min-width: 2rem;
	}
	.group-tag-halves {
		color: var(--color-info);
		background: var(--color-info-soft);
	}
	.group-tag-thirds {
		color: var(--color-violet);
		background: var(--color-violet-soft);
	}
	.group-tag-kholles {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
</style>
