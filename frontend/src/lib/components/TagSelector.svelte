<script lang="ts" generics="T extends string | number">
	import Icon from './Icon.svelte';
	import { colorForeground } from '#lib/lessons';
	let {
		options,
		selected = $bindable([]),
		legend,
		disabled = false
	}: {
		options: {
			value: T;
			label: string;
			color: string;
			icon?: string;
			disabled?: boolean;
			background?: string;
			tone?: string;
		}[];
		selected: T[];
		legend: string;
		disabled?: boolean;
	} = $props();
</script>

<fieldset class="tag-selector" {disabled}>
	<legend class="label">{legend}</legend>
	<div class="tag-options">
		{#each options as option (option.value)}<label
				class="tag-choice"
				class:chosen={selected.includes(option.value)}
				class:unavailable={disabled || option.disabled}
				class:teacher-choice={option.tone !== undefined}
				class:external={option.tone === 'external'}
				class:other={option.tone === 'other'}
				style:--teacher-background={option.background ?? option.color}
				style:--choice-color={option.color}
				style:--choice-foreground={colorForeground(option.color)}
			>
				<input
					type="checkbox"
					value={option.value}
					bind:group={selected}
					disabled={disabled || option.disabled}
				/>
				{#if option.icon}<Icon name={option.icon} size={15} />{/if}<span>{option.label}</span><span
					class="choice-check"
					aria-hidden="true"
					><Icon name={selected.includes(option.value) ? 'check' : 'plus'} size={12} /></span
				>
			</label>{/each}
	</div>
</fieldset>

<style>
	.tag-choice.teacher-choice {
		background: color-mix(in srgb, var(--choice-color) 30%, var(--color-surface));
		color: var(--color-ink);
		border-color: var(--choice-color);
		position: relative;
		isolation: isolate;
	}
	.tag-choice.teacher-choice::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: -1;
		background: var(--teacher-background);
		opacity: 0.25;
		border-radius: inherit;
	}
	.tag-choice.teacher-choice.external {
		background: var(--color-surface);
		border-color: color-mix(in srgb, var(--choice-color) 35%, var(--color-border));
	}
	.tag-choice.teacher-choice.external::before {
		opacity: 0.08;
	}
	.tag-choice.teacher-choice.other {
		background: var(--color-paper);
		color: var(--color-muted);
		border-color: var(--color-border);
	}
	.tag-choice.teacher-choice.other::before {
		opacity: 0;
	}
	.tag-choice.teacher-choice.chosen {
		outline: 2px solid var(--color-primary);
		outline-offset: 2px;
	}
</style>
