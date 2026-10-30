<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { themePreference, themeCookieValue, type ThemePreference } from '#lib/theme';
	import Icon from './Icon.svelte';
	let { initialPreference = 'system' }: { initialPreference?: ThemePreference } = $props();
	const choices = [
		{ value: 'light', label: 'Clair', icon: 'sun' },
		{ value: 'system', label: 'Périphérique', icon: 'desktop' },
		{ value: 'dark', label: 'Sombre', icon: 'moon' }
	] as const;
	let preference = $state<ThemePreference>(untrack(() => initialPreference));
	let ready = $state(false);
	const name = $props.id();
	onMount(() => {
		preference = themePreference(document.documentElement.dataset.theme);
		ready = true;
	});
	function change(value: ThemePreference): void {
		preference = value;
		document.documentElement.dataset.theme = value;
		try {
			document.cookie = themeCookieValue(value, location.protocol === 'https:');
		} catch {
			// A browser blocking cookies can still change this page's appearance.
		}
	}
</script>

<fieldset class="theme-picker" disabled={!ready}>
	<legend class="theme-label">Apparence</legend>
	<div
		class="theme-track"
		style:--position={choices.findIndex((choice) => choice.value === preference)}
	>
		<span class="theme-thumb" aria-hidden="true"></span>
		{#each choices as choice (choice.value)}
			<label class:active={preference === choice.value}>
				<input
					type="radio"
					{name}
					value={choice.value}
					checked={preference === choice.value}
					onchange={() => change(choice.value)}
				/>
				<Icon name={choice.icon} size={14} /><span>{choice.label}</span>
			</label>
		{/each}
	</div>
</fieldset>

<style>
	.theme-picker {
		min-width: 0;
	}
	.theme-label {
		font-size: 0.7rem;
		color: var(--color-muted);
		margin-bottom: 0.4rem;
	}
	.theme-track {
		position: relative;
		isolation: isolate;
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		padding: 3px;
		border: var(--border-thin);
		border-radius: 999px;
		background: var(--color-paper);
	}
	.theme-thumb {
		position: absolute;
		z-index: -1;
		top: 3px;
		bottom: 3px;
		left: 3px;
		width: calc((100% - 6px) / 3);
		border-radius: 999px;
		background: var(--color-surface);
		box-shadow: var(--shadow-panel);
		transform: translateX(calc(var(--position) * 100%));
		transition: transform 180ms ease;
	}
	label {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.35rem;
		padding: 0.55rem 0.65rem;
		font-size: 0.72rem;
		color: var(--color-muted);
		cursor: pointer;
		border-radius: 999px;
	}
	label.active {
		color: var(--color-ink);
	}
	label:focus-within {
		outline: 2px solid var(--color-primary);
		outline-offset: 1px;
	}
	input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
	}
</style>
