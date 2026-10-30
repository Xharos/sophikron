<script lang="ts">
	import { tick } from 'svelte';
	import FormattedText from './lessons/FormattedText.svelte';
	let {
		value = $bindable(''),
		color,
		id,
		disabled = false,
		required = false
	}: {
		value: string;
		color: string;
		id: string;
		disabled?: boolean;
		required?: boolean;
	} = $props();
	let input = $state<HTMLTextAreaElement>();
	async function format(marker: string, heading = false): Promise<void> {
		if (!input) return;
		let first = input.selectionStart;
		const last = input.selectionEnd;
		if (heading) first = value.lastIndexOf('\n', first - 1) + 1;
		const selected = value.slice(first, last) || (heading ? 'Titre' : 'texte');
		const inserted = heading ? marker + ' ' + selected : marker + selected + marker;
		value = value.slice(0, first) + inserted + value.slice(last);
		await tick();
		input.focus();
		input.setSelectionRange(first, first + inserted.length);
	}
</script>

<div class="format-toolbar" role="group" aria-label="Mise en forme du texte">
	{#each [{ label: 'Gras', marker: '**' }, { label: 'Italique', marker: '*' }, { label: 'Couleur', marker: '==' }, { label: 'Section', marker: '#' }, { label: 'Sous-section', marker: '##' }] as option (option.label)}<button
			type="button"
			class="button is-light is-small"
			{disabled}
			onclick={() => format(option.marker, option.marker.startsWith('#'))}>{option.label}</button
		>{/each}
</div>
<textarea
	{id}
	class="textarea"
	bind:this={input}
	bind:value
	rows="8"
	maxlength="3000"
	{disabled}
	{required}></textarea>
<p class="help">
	*italique*, **gras**, ==coloré==, # Section, ## Sous-section. {value.length}/3000 caractères.
</p>
<div class="text-preview">
	<p class="mini-label mb-2">Aperçu</p>
	<FormattedText text={value || 'Votre texte apparaîtra ici.'} {color} />
</div>

<style>
	.format-toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-bottom: 0.5rem;
	}
	.text-preview {
		padding: 1rem;
		margin-top: 1rem;
		border: var(--border-thin);
		border-radius: 0.6rem;
	}
</style>
