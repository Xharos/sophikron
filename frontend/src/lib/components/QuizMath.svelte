<script lang="ts">
	import katex from 'katex';
	import 'katex/dist/katex.min.css';

	let { text }: { text: string } = $props();

	const parts = $derived.by(() => {
		const content: { plain: string; math?: string }[] = [];
		const formulas = /\$\$([\s\S]+?)\$\$|(?<!\\)\$([^$\n]+?)\$/g;
		let start = 0;
		for (const match of text.matchAll(formulas)) {
			const source = match[1] ?? match[2];
			content.push({ plain: text.slice(start, match.index).replaceAll('\\$', '$') });
			try {
				content.push({
					plain: match[0],
					math: katex.renderToString(source, {
						displayMode: match[1] !== undefined,
						trust: false,
						maxExpand: 100,
						maxSize: 20,
						strict: 'ignore'
					})
				});
			} catch {
				content.push({ plain: match[0] });
			}
			start = match.index + match[0].length;
		}
		content.push({ plain: text.slice(start).replaceAll('\\$', '$') });
		return content;
	});
</script>

<span class="quiz-math">
	{#each parts as part, index (index)}{#if part.math}
			<!-- eslint-disable-next-line svelte/no-at-html-tags -- Render only KaTeX output with trust disabled. -->
			{@html part.math}
		{:else}{part.plain}{/if}{/each}
</span>

<style>
	.quiz-math {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.quiz-math :global(.katex-display) {
		overflow-x: auto;
		overflow-y: hidden;
	}
</style>
