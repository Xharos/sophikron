<script lang="ts" generics="T extends string | number">
	import { colorForeground } from '#lib/lessons';
	import Icon from './Icon.svelte';
	let {
		label,
		value = $bindable(),
		choices,
		disabled = false
	}: {
		label: string;
		value: T;
		choices: { value: T; label: string; icon: string; color?: string }[];
		disabled?: boolean;
	} = $props();
	const name = $props.id();
</script>

<fieldset class="field" {disabled}>
	<legend class="label">{label}</legend>
	<div class="visual-choices">
		{#each choices as choice (choice.value)}
			<label class="visual-choice" class:selected={value === choice.value}>
				<input type="radio" {name} value={choice.value} bind:group={value} required />
				<span
					class="choice-icon"
					style:background={choice.color ?? 'var(--color-primary)'}
					style:color={choice.color ? colorForeground(choice.color) : 'var(--color-on-primary)'}
					><Icon name={choice.icon} size={22} /></span
				>
				<span class="choice-label">{choice.label}</span>
				<span class="choice-check" aria-hidden="true"><Icon name="check" size={14} /></span>
			</label>
		{/each}
	</div>
</fieldset>

<style>
	.visual-choices {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr));
		gap: 0.5rem;
		max-height: 19rem;
		overflow-y: auto;
		padding: 0.25rem;
	}
	.visual-choice {
		position: relative;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.7rem;
		border: 2px solid var(--color-border);
		border-radius: 0.75rem;
		background: var(--color-surface);
		cursor: pointer;
	}
	.visual-choice:hover,
	.selected {
		border-color: var(--color-primary, #4361ee);
		background: color-mix(in srgb, var(--color-primary, #4361ee) 6%, var(--color-surface));
	}
	.visual-choice:focus-within {
		outline: 2px solid var(--color-primary, #4361ee);
		outline-offset: 2px;
	}
	input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
	}
	.choice-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: 0 0 2.5rem;
		height: 2.5rem;
		border-radius: 0.65rem;
	}
	.choice-label {
		flex: 1;
		font-size: 0.85rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.choice-check {
		visibility: hidden;
		color: var(--color-primary, #4361ee);
	}
	.selected .choice-check {
		visibility: visible;
	}
	fieldset:disabled .visual-choice {
		opacity: 0.6;
		cursor: default;
	}
</style>
