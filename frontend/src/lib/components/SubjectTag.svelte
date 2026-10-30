<script lang="ts">
	import type { Subject } from '#lib/site';
	import Icon from './Icon.svelte';
	let { subject }: { subject: Pick<Subject, 'name' | 'icon' | 'color'> } = $props();
</script>

<span class="subject-badge" style:--subject-color={subject.color}>
	<Icon name={subject.icon} size={14} />{subject.name}
</span>

<style>
	.subject-badge {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--color-ink);
		background: color-mix(in srgb, var(--subject-color) 15%, var(--color-surface));
		border: 1px solid color-mix(in srgb, var(--subject-color) 40%, var(--color-border));
		vertical-align: middle;
		max-width: 100%;
		overflow-wrap: anywhere;
	}
</style>
