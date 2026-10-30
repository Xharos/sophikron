<script lang="ts" generics="T extends string | number">
	import Icon from './Icon.svelte';
	import { colorForeground } from '#lib/lessons';
	let {
		legend,
		options,
		value,
		onchange,
		disabled = false,
		onclear
	}: {
		legend: string;
		options: { value: T; label: string; color?: string; disabled?: boolean; secondary?: boolean }[];
		value: T | null;
		onchange: (value: T) => void;
		disabled?: boolean;
		onclear?: () => void;
	} = $props();
	const name = $props.id();
</script>

<fieldset class="tag-selector field" {disabled}>
	<legend class="label">{legend}</legend>
	<div class="tag-options">
		{#each options as option (option.value)}
			{@const color = option.color ?? '#244BC1'}
			<label
				class="tag-choice"
				class:chosen={value === option.value}
				class:secondary={option.secondary && value !== option.value}
				class:unavailable={disabled || option.disabled}
				style:--choice-color={color}
				style:--choice-foreground={colorForeground(color)}
			>
				<input
					type="radio"
					{name}
					value={option.value}
					checked={value === option.value}
					disabled={disabled || option.disabled}
					onclick={() => {
						if (onclear && value === option.value) {
							onclear();
						}
					}}
					onkeydown={(event) => {
						if (onclear && event.key === ' ' && value === option.value) {
							event.preventDefault();
							onclear();
						}
					}}
					onchange={() => onchange(option.value)}
				/>
				<span>{option.label}</span>
				<span class="choice-check" aria-hidden="true"
					><Icon name={value === option.value ? 'check' : 'plus'} size={12} /></span
				>
			</label>
		{/each}
	</div>
</fieldset>

<style>
	.tag-choice.secondary:not(:hover):not(:focus-within) {
		background: var(--color-subtle);
		color: var(--color-muted);
		border-color: var(--color-border);
		font-weight: 400;
		box-shadow: none;
	}
</style>
