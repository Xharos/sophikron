<script lang="ts">
	import { formattedBlocks, type TextPart } from '#lib/lessons';
	import { readableColor } from '#lib/colors';
	let { text, color }: { text: string; color: string } = $props();
	const lines = $derived(formattedBlocks(text));
</script>

<div
	class="lesson-text"
	style:--text-on-light={readableColor(color, '#f7f8fa')}
	style:--text-on-dark={readableColor(color, '#1b2532')}
>
	{#snippet lineContent(parts: TextPart[])}{#each parts as part, index (index)}<span
				class:bold={part.bold}
				class:italic={part.italic}
				class:colored={part.colored}>{part.text}</span
			>{/each}{/snippet}
	{#each lines as line, index (index)}{#if line.level === 1}<h2>
				{@render lineContent(line.parts)}
			</h2>{:else if line.level === 2}<h3>{@render lineContent(line.parts)}</h3>{:else}<div
				class="text-line"
			>
				{@render lineContent(line.parts)}{#if !line.parts.length}<br />{/if}
			</div>{/if}{/each}
</div>

<style>
	.lesson-text {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		line-height: 1.85;
	}
	.bold {
		font-weight: 750;
	}
	h2 {
		font-size: 1.5rem;
		font-weight: 750;
		margin: 1rem 0 0.5rem;
	}
	h3 {
		font-size: 1.2rem;
		font-weight: 700;
		margin: 0.8rem 0 0.4rem;
	}
	.italic {
		font-style: italic;
	}
	.colored {
		color: light-dark(var(--text-on-light), var(--text-on-dark));
		border-radius: 3px;
		padding: 0 0.12em;
	}
</style>
