<script lang="ts">
	import type { Subject } from '#lib/site';
	import { colorForeground } from '#lib/lessons';
	import Icon from './Icon.svelte';
	let { subject }: { subject: Pick<Subject, 'name' | 'icon' | 'color'> } = $props();
</script>

<span
	class="subject-identity"
	style:--promotion-color={subject.color}
	style:--promotion-foreground={colorForeground(subject.color)}
>
	<span class="card-emblem" aria-hidden="true"><Icon name={subject.icon} size={21} /></span>
	<strong>{subject.name}</strong>
</span>

<style>
	.subject-identity {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		min-width: 0;
		color: var(--color-ink);
	}
	.card-emblem {
		flex-shrink: 0;
		background: var(--promotion-color);
		color: var(--promotion-foreground);
		width: 2.5rem;
		height: 2.5rem;
	}
	strong {
		font-size: 0.8rem;
		line-height: 1.35;
		overflow-wrap: anywhere;
		text-align: left;
	}
</style>
