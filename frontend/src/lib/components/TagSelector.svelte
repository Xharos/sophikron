<script lang="ts" generics="T extends string | number">
	import Icon from './Icon.svelte';
	import { colorForeground } from '#lib/lessons';
	let {
		options,
		selected = $bindable([]),
		legend,
		disabled = false
	}: {
		options: { value: T; label: string; color: string; icon?: string; disabled?: boolean }[];
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
